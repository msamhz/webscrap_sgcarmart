from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import re

def collect_listing_links(main_url, max_pages=20):
    """
    Crawl all paginated listing links from sgcarmart Used Cars search results pages.

    Args:
        main_url (str): The URL of the first result page to start scraping from.
        max_pages (int): Maximum number of pages to paginate through (guard against infinite loops).

    Returns:
        Set[str]: A set containing all unique car listing URLs found.
    """
    def extract_links_from_page(html):
        soup = BeautifulSoup(html, "html.parser")
        listing_divs = soup.find_all("div", id=re.compile(r"^listing_\d+$"))
        links = []
        for div in listing_divs:
            for a in div.find_all("a", class_="styles_text_link__wBaHL"):
                href = a.get("href")
                if href and href.startswith("https"):
                    links.append(href)
        return links

    options = webdriver.ChromeOptions()
    # Uncomment if running on server: options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 20)

    driver.get(main_url)

    all_links = set()
    page_idx = 1

    try:
        while page_idx <= max_pages:
            # Wait for listings to load
            wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div[id^='listing_']")))
            # Collect links from current page
            all_links.update(extract_links_from_page(driver.page_source))

            # Find next button in paginator (desktop)
            next_btn = driver.find_element(By.CSS_SELECTOR,
                '#desktopPaginationContainer button[class*="right_control"]')

            # Stop if Next is disabled
            if "disabled" in next_btn.get_attribute("class") or not next_btn.is_enabled():
                break

            # Remember a listing element to detect page change
            old_first = driver.find_element(By.CSS_SELECTOR, "div[id^='listing_']")

            # Click Next (using JS for reliability)
            driver.execute_script("arguments[0].click();", next_btn)

            # Wait for listings to change (old page should be stale)
            wait.until(EC.staleness_of(old_first))
            page_idx += 1
    finally:
        driver.quit()

    return all_links

def extract_sgcarmart_car_details(url):
    import requests
    from bs4 import BeautifulSoup
    import re
    import json

    # Configure headers to mimic a real browser
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
    }

    # Make the request
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    # Parse the HTML content
    soup = BeautifulSoup(response.text, 'html.parser')

    # Find the <script> tag containing relevant data
    script = next(
        (tag for tag in soup.find_all("script")
         if "success" in tag.text and "coe" in tag.text and "depreciation" in tag.text),
        None
    )
    
    def clean_value(key, value):
        """
        Clean up the extracted value for any of the wanted keys.
        For numeric/currency-like values: remove non-numeric, non-dot, non-minus chars.
        For others: just strip whitespace.
        """
        # Always try to normalize money/numbers (contains $ or numbers or unit suffix)
        # If it contains digits, possibly with currency symbols or known suffixes, try to extract the main number
        if any(char.isdigit() for char in value):
            # Remove currency markers ($), commas, spaces, slashes, "yr", "km", "cc", etc.
            clean = value
            # Remove "$", ",", spaces
            clean = re.sub(r'[,$]', '', clean)
            # Remove common unit suffixes/spaces (will still keep decimals and / where relevant)
            clean = re.sub(r'\s*(/yr|yr|km|cc|as of today|/)', '', clean, flags=re.IGNORECASE)
            # Remove any leftover non-numeric except dot
            clean = re.sub(r'[^\d.]', '', clean)
            return clean
        else:
            return value.strip()
    
    def clean_js_escapes(s):
        # Decode unicode escapes and remove unnecessary backslashes from quotes etc.
        s = s.encode('utf-8').decode('unicode_escape')
        s = s.replace('\\/', '/')
        s = s.replace('\\\\', '\\')
        return s

    cleaned_script10_str = clean_js_escapes(script.text if hasattr(script, 'text') else script)

    def get_carmodel(cleaned_script10_str):
        match = re.search(r'"car_model"\s*:\s*"([^"]+)"', cleaned_script10_str, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def get_regdate(cleaned_script10_str):
        match = re.search(r'"reg_date"\s*:\s*"([^"]+)"', cleaned_script10_str, re.IGNORECASE)
        if match:
            return match.group(1)
        return None
    
    def get_type_of_vehicle(cleaned_script10_str):
        # Handles both object and string representations
        dict_match = re.search(
            r'"type_of_vehicle"\s*:\s*\{(.*?)\}', cleaned_script10_str, re.IGNORECASE | re.DOTALL
        )
        if dict_match:
            dict_str = '{' + dict_match.group(1) + '}'
            dict_str = re.sub(r',\s*\}$', '}', dict_str)
            try:
                dict_str_cleaned = dict_str.replace('\\"', '"').replace("'", '"')
                if dict_str_cleaned.count('{') != dict_str_cleaned.count('}'):
                    dict_str_cleaned = dict_str_cleaned + '}'
                type_obj = json.loads(dict_str_cleaned)
                if isinstance(type_obj, dict) and 'text' in type_obj:
                    return type_obj['text'].strip()
                return type_obj
            except Exception:
                pass
        simple_match = re.search(
            r'"type_of_vehicle"\s*:\s*"([^"]+)"', cleaned_script10_str, re.IGNORECASE
        )
        if simple_match:
            return simple_match.group(1).strip()
        simple_unquoted = re.search(
            r'"type_of_vehicle"\s*:\s*([^,"\}\r\n]+)', cleaned_script10_str, re.IGNORECASE
        )
        if simple_unquoted:
            return simple_unquoted.group(1).strip()
        return None

    def extract_car_details(cleaned_script10_str, clean_value_func):
        wanted_keys = [
            "price","Transmission", "Fuel Type", "Engine Capacity", "Curb Weight", "Power",
            "Road Tax", "Deregistration Value", "COE", "OMV", "ARF",
            "mileage", "owners", "dealer", "dereg_value", "engine_cap"
        ]
        wanted_keys_small = [k.replace(" ", "_").lower() for k in wanted_keys]
        results_smallcaps_cleaned = {}
        for orig, key in zip(wanted_keys, wanted_keys_small):
            pat = re.compile(
                r'["\']?' + re.escape(key) + r'["\']?\s*:\s*["\']?([^"\'}<\n]+)',
                re.IGNORECASE
            )
            if key == "mileage":
                matches = pat.findall(cleaned_script10_str)
                if len(matches) >= 2:
                    value = matches[1].strip()
                elif len(matches) == 1:
                    value = matches[0].strip()
                else:
                    value = None
                if value is not None:
                    value_noparens = re.sub(r'\([^\)]*\)', '', value).strip()
                    clean = clean_value_func(key, value_noparens)
                    results_smallcaps_cleaned[key] = clean
            else:
                match = pat.search(cleaned_script10_str)
                if match:
                    value = match.group(1).strip()
                    value_noparens = re.sub(r'\([^\)]*\)', '', value).strip()
                    clean = clean_value_func(key, value_noparens)
                    results_smallcaps_cleaned[key] = clean
        return results_smallcaps_cleaned

    carmodel = get_carmodel(cleaned_script10_str)
    type_of_vehicle = get_type_of_vehicle(cleaned_script10_str)
    regdate = get_regdate(cleaned_script10_str)
    
    results_smallcaps_cleaned = extract_car_details(cleaned_script10_str, clean_value)
    results_smallcaps_cleaned['reg_date'] = regdate
    results_smallcaps_cleaned['carmodel'] = carmodel
    results_smallcaps_cleaned['type_of_vehicle'] = type_of_vehicle
    results_smallcaps_cleaned['url'] = url
    
    
    return results_smallcaps_cleaned


def get_or_append_carlist_df(details, data_folder="data"):
    """
    If a CSV file exists in the data_folder, append the new details as a row.
    If none exists, create a new one with the first details.
    """
    import os
    import pandas as pd
    from datetime import datetime

    os.makedirs(data_folder, exist_ok=True)
    csv_files = [f for f in os.listdir(data_folder) if f.startswith("carlist_") and f.endswith(".csv")]

    if csv_files:
        # Use most recent file
        csv_files_sorted = sorted(
            csv_files,
            key=lambda fn: fn.split("_")[1].replace(".csv", ""),
            reverse=True
        )
        csv_path = os.path.join(data_folder, csv_files_sorted[0])
        df = pd.read_csv(csv_path)

        # Append new details
        df_new = pd.DataFrame([details])
        df = pd.concat([df, df_new], ignore_index=True)
        df.to_csv(csv_path, index=False)
    else:
        # No CSV exists, create new one
        timestamp = datetime.now().strftime("%Y%m%d")
        csv_path = os.path.join(data_folder, f"carlist_{timestamp}.csv")
        df = pd.DataFrame([details])
        df.to_csv(csv_path, index=False)

    return df