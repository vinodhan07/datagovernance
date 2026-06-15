import os
import pandas as pd
import numpy as np
from sqlalchemy import create_engine

# single source of truth for MariaDB url
MARIADB_URL = "mysql+pymysql://root:root123@localhost:3307/governance_db"

def generate_or_download_data():
    url = "https://archive.ics.uci.edu/ml/machine-learning-databases/adult/adult.data"
    columns = [
        "age", "workclass", "fnlwgt", "education", "education_num",
        "marital_status", "occupation", "relationship", "race", "sex",
        "capital_gain", "capital_loss", "hours_per_week", "native_country", "income"
    ]
    
    pth", "HS-grad", "Masters", "Doctorate"], n_rows),
            "education_num": np.random.randint(1, 16, n_rows),
            "marital_status": np.random.choice(["Married-civ-spouse", "Never-married", "Divorced", "Separated"], n_rows),
            "occupation": np.random.choice(["Tech-support", "Craft-repair", "Sales", "Exec-managerial", "Prof-specialty"], n_rows),
            "relationship": np.random.choice(["Wife", "Own-child", "Husband", "Not-in-family", "Other-relative"], n_rows),
            "race": np.random.choice(["White", "Black", "Asian-Pac-Islander", "rint("📥 Attempting to download UCI Adult Income dataset...")
    try:
        df = pd.read_csv(url, names=columns, na_values=" ?", skipinitialspace=True, timeout=10)
        print("✅ Downloaded UCI Adult Income dataset successfully!")
    except Exception as e:
        print(f"⚠️ Failed to download data ({e}). Generating synthetic customer data...")
        np.random.seed(42)
        n_rows = 1000
        df = pd.DataFrame({
            "age": np.random.randint(18, 75, n_rows),
            "workclass": np.random.choice(["Private", "Self-emp", "State-gov", "Federal-gov"], n_rows),
            "fnlwgt": np.random.randint(20000, 500000, n_rows),
            "education": np.random.choice(["Bachelors", "Some-college", "11Amer-Indian-Eskimo", "Other"], n_rows),
            "sex": np.random.choice(["Male", "Female"], n_rows),
            "capital_gain": np.random.choice([0, np.random.randint(1000, 50000)], n_rows, p=[0.9, 0.1]),
            "capital_loss": np.random.choice([0, np.random.randint(100, 5000)], n_rows, p=[0.95, 0.05]),
            "hours_per_week": np.random.randint(10, 80, n_rows),
            "native_country": np.random.choice(["United-States", "Mexico", "Philippines", "Germany", "Canada"], n_rows),
            "income": np.random.choice(["<=50K", ">50K"], n_rows, p=[0.75, 0.25])
        })
        print(f"✅ Generated {n_rows} rows of synthetic customer data.")

    df.dropna(inplace=True)
    engine = create_engine(MARIADB_URL)
    print("📤 Writing data to target MariaDB table 'adult_income'...")
    df.to_sql("adult_income", engine, if_exists="replace", index=False)
    print("🎉 Table 'adult_income' successfully created/updated in MariaDB!")

if __name__ == "__main__":
    generate_or_download_data()
