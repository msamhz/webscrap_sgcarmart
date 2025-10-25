from tqdm import tqdm
from tools import collect_listing_links, extract_sgcarmart_car_details, get_or_append_carlist_df
import os
import pandas as pd
import numpy as np
import re
import yaml
from datetime import datetime


def main():
    main_url = input("Please enter the main URL for car listings: ")
    max_pages = int(input("Please enter the maximum number of pages to scrape: ")  ) 
    list_of_cars = collect_listing_links(main_url, max_pages = max_pages)

    for cars in tqdm(list_of_cars, desc="Processing cars", unit="car"):
        import time

        max_retries = 5
        for attempt in range(max_retries):
            details = extract_sgcarmart_car_details(cars)
            if len(details) == 18:
                break
            time.sleep(1)
        else:
            print(f"Warning: Details for {cars} could not be extracted properly after {max_retries} attempts. Got: {details}")
            
        get_or_append_carlist_df(details)
        
    print("="*60)
    print("📝  Note: Raw data may contain duplicate entries!")
    print("✨  Preprocessing will automatically remove duplicates from the dataset.")
    print("="*60)
    
    def process_carlist_data(data_folder='data', params_path='params.yaml'):
        # Get most recent carlist CSV in the folder
        csv_files = [f for f in os.listdir(data_folder) if f.startswith("carlist_") and f.endswith(".csv")]
        if not csv_files:
            raise FileNotFoundError("No carlist CSV files found in the given data folder.")
        csv_files_sorted = sorted(
            csv_files,
            key=lambda fn: fn.split("_")[1].replace(".csv", ""),
            reverse=True
        )
        csv_path = os.path.join(data_folder, csv_files_sorted[0])
        print(f"Processing {csv_path}")
        
        df = pd.read_csv(csv_path)

        df = df[~df['transmission'].isnull()].copy(deep=True)

        # Parse registration date
        # The current format may fail if data does not match '%d-%b-%y';
        # Instead, use 'format="mixed"' to allow pandas to infer format per entry:
        df['reg_date'] = pd.to_datetime(df['reg_date'], format='mixed', dayfirst=True, errors='coerce')

        today = pd.Timestamp(datetime.today().date())

        def years_months_left(reg_date, lifespan_years=10):
            end_date = reg_date + pd.DateOffset(years=lifespan_years)
            delta = end_date - today
            if delta.days < 0:
                return "Expired"
            years = delta.days // 365
            months = (delta.days % 365) // 30
            return f"{years} yr {months} mth"

        df['years_months_left'] = df['reg_date'].apply(years_months_left)

        # helpers
        def parse_money(x):
            x = re.sub(r"[^0-9.]", "", str(x)) if pd.notna(x) else ""
            return float(x) if x else np.nan

        # Load PQP params from yaml
        with open(params_path, "r") as f:
            params = yaml.safe_load(f)

        default_cat = params["pqp"].get("default_cat", "A")
        PQP10 = float(params["pqp"]["categories"][default_cat]["ten_year"])
        PQP5  = float(params["pqp"]["categories"][default_cat]["five_year"])

        # value calculations
        df["ARF_val"] = df["arf"].apply(parse_money)
        df["dereg_val_at_10y"] = (df["ARF_val"] * 0.5).round(0)
        df["pqp_est_10y"] = PQP10
        df["pqp_est_5y"]  = PQP5
        df["extend_net_value_10y"] = df["dereg_val_at_10y"] - df["pqp_est_10y"]
        df["extend_net_value_5y"]  = df["dereg_val_at_10y"] - df["pqp_est_5y"]
        df['cost_minus_dereg'] = df['price'] - df['dereg_val_at_10y']
        # monthly consumption worth 
        def months_left_string_to_int(x):
            if x == "Expired":
                return np.nan
            try:
                return int(x.split()[0])*12 + int(x.split()[2])
            except Exception:
                return np.nan
        months_left = df['years_months_left'].apply(months_left_string_to_int)
        df['monthly_consumption_worth'] = df['cost_minus_dereg'] / months_left

        df = df.sort_values('extend_net_value_10y', ascending=False).reset_index(drop=True)
        
        df = df.drop_duplicates().reset_index(drop=True)
        
        processed_csv_path = csv_path.replace(".csv", "_processed.csv")
        df.to_csv(processed_csv_path, index=False)
        
        print(f"Processed data saved to {processed_csv_path}. (Duplicates removed.)")
        
        return df
    
    process_carlist_data()

if __name__ == "__main__":
    main()