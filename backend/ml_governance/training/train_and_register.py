import os
import pandas as pd
import numpy as np
import mlflow
import mlflow.sklearn
from mlflow.models.signature import infer_signature
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sqlalchemy import create_engine

MARIADB_URL = os.getenv("MARIADB_URL", "mysql+pymysql://root:root123@localhost:3307/governance_db")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")

def train_and_register():
    print(f"🔗 Connecting to MariaDB database to load 'adult_income' table...")
    engine = create_engine(MARIADB_URL)
    try:
        df = pd.read_sql("SELECT * FROM adult_income", engine)
    except Exception as e:
        print(f"❌ Failed to read from database: {e}. Please run generate_sample_data.py first.")
        return

    print(f"📊 Loaded {len(df)} rows. Preprocessing data...")
    df = df.copy()
    
    # Encode target column
    if "income" in df.columns:
        df["income"] = (df["income"].astype(str).str.strip().isin([">50K", "1", "1.0", "y", "yes"])).astype(int)
    else:
        # Generate dummy target if not exists
        df["income"] = np.random.randint(0, 2, len(df))
        
    target_col = "income"
    
    # Categorical columns encoding
    cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
    le = LabelEncoder()
    for col in cat_cols:
        df[col] = le.fit_transform(df[col].astype(str))

    feature_cols = [c for c in df.columns if c not in [target_col, "fnlwgt"]]
    X = df[feature_cols]
    y = df[target_col]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    print(f"🧪 Setting MLflow tracking URI to {MLFLOW_TRACKING_URI}...")
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment("Synthetic_Customer_Experiment")

    print("🚀 Training Random Forest model...")
    model = RandomForestClassifier(n_estimators=50, max_depth=5, random_state=42)
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    acc = accuracy_score(y_test, preds)
    print(f"📈 Model Accuracy: {acc:.4f}")

    # Infer model signature
    signature = infer_signature(X_train, y_train)

    print("📤 Logging run & model to MLflow...")
    with mlflow.start_run(run_name="synthetic_classifier_run") as run:
        mlflow.log_params({
            "model_type": "RandomForestClassifier",
            "n_estimators": 50,
            "max_depth": 5,
            "train_size": len(X_train),
            "test_size": len(X_test)
        })
        mlflow.log_metric("accuracy", acc)

        # Log model with signature and register it
        mlflow.sklearn.log_model(
            sk_model=model,
            artifact_path="model",
            signature=signature,
            registered_model_name="synthetic_customer_classifier"
        )
        run_id = run.info.run_id
        print(f"🎉 Model registered as 'synthetic_customer_classifier' (Run ID: {run_id[:8]})!")

if __name__ == "__main__":
    train_and_register()
