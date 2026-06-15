"""
ML Model Training with Bias, Drift & Data Quality Monitoring
Dataset: Adult Income (UCI) - predicts if income >50K
Tracks: Accuracy, Fairness metrics, Feature drift, Data quality issues
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import mlflow
import mlflow.sklearn
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.metrics import (
    accuracy_score, f1_score, roc_auc_score,
    classification_report, confusion_matrix
)
from sklearn.pipeline import Pipeline
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
import os

# ─────────────────────────────────────────────
# 1. LOAD DATA
# ─────────────────────────────────────────────

def load_adult_data():
    """Load UCI Adult Income dataset."""
    url = "https://archive.ics.uci.edu/ml/machine-learning-databases/adult/adult.data"
    columns = [
        "age", "workclass", "fnlwgt", "education", "education_num",
        "marital_status", "occupation", "relationship", "race", "sex",
        "capital_gain", "capital_loss", "hours_per_week", "native_country", "income"
    ]
    print("📥 Downloading Adult Income dataset...")
    df = pd.read_csv(url, names=columns, na_values=" ?", skipinitialspace=True)
    print(f"✅ Loaded {len(df):,} rows, {df.shape[1]} columns")
    return df


# ─────────────────────────────────────────────
# 2. DATA QUALITY CHECK
# ─────────────────────────────────────────────

def check_data_quality(df):
    """Return data quality metrics dict."""
    total = len(df)
    metrics = {
        "dq_total_rows": total,
        "dq_total_columns": df.shape[1],
        "dq_missing_values_total": int(df.isnull().sum().sum()),
        "dq_missing_pct": round(df.isnull().sum().sum() / (total * df.shape[1]) * 100, 2),
        "dq_duplicate_rows": int(df.duplicated().sum()),
        "dq_duplicate_pct": round(df.duplicated().sum() / total * 100, 2),
    }
    # Per-column missing
    for col in df.columns:
        missing = df[col].isnull().sum()
        if missing > 0:
            metrics[f"dq_missing_{col}"] = int(missing)

    print(f"\n📊 Data Quality:")
    print(f"   Rows: {total:,} | Missing: {metrics['dq_missing_values_total']} ({metrics['dq_missing_pct']}%) | Duplicates: {metrics['dq_duplicate_rows']}")
    return metrics


# ─────────────────────────────────────────────
# 3. PREPROCESSING
# ─────────────────────────────────────────────

def preprocess(df):
    """Clean and encode the dataframe."""
    df = df.copy()
    df.dropna(inplace=True)
    df["income"] = (df["income"].str.strip() == ">50K").astype(int)

    cat_cols = ["workclass", "education", "marital_status",
                "occupation", "relationship", "race", "sex", "native_country"]
    le = LabelEncoder()
    for col in cat_cols:
        df[col] = le.fit_transform(df[col].astype(str))

    feature_cols = [c for c in df.columns if c not in ["income", "fnlwgt"]]
    X = df[feature_cols]
    y = df["income"]

    # Save sex and race for bias analysis
    protected = df[["sex", "race"]].copy()
    return X, y, protected, feature_cols


# ─────────────────────────────────────────────
# 4. BIAS METRICS
# ─────────────────────────────────────────────

def compute_bias_metrics(y_true, y_pred, protected_df):
    """
    Compute fairness metrics for gender and race.
    - Demographic Parity Difference (DPD): difference in positive prediction rates
    - Equalized Odds Difference (EOD): difference in TPR between groups
    """
    metrics = {}

    for attr in ["sex", "race"]:
        groups = protected_df[attr].unique()
        pred_rates = {}
        tprs = {}

        for g in groups:
            mask = protected_df[attr] == g
            preds_g = y_pred[mask]
            true_g = y_true[mask]
            pred_rates[g] = preds_g.mean()
            tp = ((preds_g == 1) & (true_g == 1)).sum()
            fn = ((preds_g == 0) & (true_g == 1)).sum()
            tprs[g] = tp / (tp + fn) if (tp + fn) > 0 else 0

        dpd = max(pred_rates.values()) - min(pred_rates.values())
        eod = max(tprs.values()) - min(tprs.values())

        metrics[f"bias_{attr}_demographic_parity_diff"] = round(float(dpd), 4)
        metrics[f"bias_{attr}_equalized_odds_diff"] = round(float(eod), 4)

        print(f"\n⚖️  Bias ({attr}):")
        print(f"   Demographic Parity Diff: {dpd:.4f}  {'✅ Fair' if dpd < 0.1 else '⚠️  Unfair'}")
        print(f"   Equalized Odds Diff:     {eod:.4f}  {'✅ Fair' if eod < 0.1 else '⚠️  Unfair'}")

    return metrics


# ─────────────────────────────────────────────
# 5. DRIFT SIMULATION
# ─────────────────────────────────────────────

def simulate_drift(X_train, X_test):
    """
    Simulate feature drift by comparing train vs test distributions.
    Uses Population Stability Index (PSI) — PSI > 0.2 = significant drift.
    """
    def psi(expected, actual, bins=10):
        eps = 1e-8
        mn = min(expected.min(), actual.min())
        mx = max(expected.max(), actual.max())
        breakpoints = np.linspace(mn, mx, bins + 1)
        exp_counts = np.histogram(expected, bins=breakpoints)[0] + eps
        act_counts = np.histogram(actual, bins=breakpoints)[0] + eps
        exp_pct = exp_counts / exp_counts.sum()
        act_pct = act_counts / act_counts.sum()
        return float(np.sum((act_pct - exp_pct) * np.log(act_pct / exp_pct)))

    # Simulate production drift: shift age and hours_per_week
    X_drifted = X_test.copy()
    X_drifted["age"] = X_drifted["age"] + np.random.normal(5, 2, len(X_drifted))
    X_drifted["hours_per_week"] = X_drifted["hours_per_week"] * 1.15

    drift_metrics = {}
    numeric_cols = X_train.select_dtypes(include=np.number).columns

    print("\n🌊 Feature Drift (PSI):")
    for col in numeric_cols:
        score = psi(X_train[col].values, X_drifted[col].values)
        drift_metrics[f"drift_psi_{col}"] = round(score, 4)
        flag = "🔴 HIGH" if score > 0.2 else ("🟡 MOD" if score > 0.1 else "🟢 OK")
        print(f"   {col:<20} PSI={score:.4f}  {flag}")

    return drift_metrics, X_drifted


# ─────────────────────────────────────────────
# 6. PLOTS
# ─────────────────────────────────────────────

def make_plots(y_test, y_pred, X_train, X_drifted, feature_cols, protected_df_test, run_dir):
    os.makedirs(run_dir, exist_ok=True)

    # --- Confusion matrix ---
    cm = confusion_matrix(y_test, y_pred)
    fig, ax = plt.subplots(figsize=(5, 4))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", ax=ax,
                xticklabels=["<=50K", ">50K"], yticklabels=["<=50K", ">50K"])
    ax.set_title("Confusion Matrix", fontweight="bold")
    ax.set_xlabel("Predicted"); ax.set_ylabel("Actual")
    plt.tight_layout()
    cm_path = os.path.join(run_dir, "confusion_matrix.png")
    plt.savefig(cm_path, dpi=100); plt.close()

    # --- Drift comparison (age) ---
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, col in zip(axes, ["age", "hours_per_week"]):
        ax.hist(X_train[col], bins=30, alpha=0.6, label="Train", color="#3B82F6")
        ax.hist(X_drifted[col], bins=30, alpha=0.6, label="Production (drifted)", color="#EF4444")
        ax.set_title(f"Drift: {col}", fontweight="bold")
        ax.legend()
    plt.suptitle("Feature Distribution Drift", fontsize=13, fontweight="bold")
    plt.tight_layout()
    drift_path = os.path.join(run_dir, "drift_plot.png")
    plt.savefig(drift_path, dpi=100); plt.close()

    # --- Bias: prediction rate by sex ---
    sex_map = {0: "Female", 1: "Male"}
    pred_rates = []
    for code, name in sex_map.items():
        mask = protected_df_test["sex"] == code
        if mask.sum() > 0:
            rate = y_pred[mask].mean()
            pred_rates.append({"Group": name, "Positive Pred Rate": rate})
    df_bias = pd.DataFrame(pred_rates)

    fig, ax = plt.subplots(figsize=(5, 4))
    colors = ["#8B5CF6", "#3B82F6"]
    bars = ax.bar(df_bias["Group"], df_bias["Positive Pred Rate"], color=colors, width=0.4)
    ax.set_title("Demographic Parity by Gender", fontweight="bold")
    ax.set_ylabel("Rate of >50K Prediction")
    ax.set_ylim(0, 1)
    for bar, val in zip(bars, df_bias["Positive Pred Rate"]):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                f"{val:.2%}", ha="center", fontweight="bold")
    plt.tight_layout()
    bias_path = os.path.join(run_dir, "bias_gender.png")
    plt.savefig(bias_path, dpi=100); plt.close()

    return cm_path, drift_path, bias_path


# ─────────────────────────────────────────────
# 7. MAIN TRAINING + MLFLOW LOGGING
# ─────────────────────────────────────────────

def train_and_log(model_name, model, X_train, X_test, y_train, y_test,
                  protected_test, dq_metrics, X_train_raw):

    with mlflow.start_run(run_name=model_name):

        # --- Train ---
        print(f"\n🚀 Training: {model_name}")
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1] if hasattr(model, "predict_proba") else None

        # --- Performance metrics ---
        acc = accuracy_score(y_test, y_pred)
        f1  = f1_score(y_test, y_pred)
        auc = roc_auc_score(y_test, y_prob) if y_prob is not None else 0.0

        print(f"   Accuracy: {acc:.4f} | F1: {f1:.4f} | AUC: {auc:.4f}")

        # --- Bias metrics ---
        bias_metrics = compute_bias_metrics(
            y_test.values, y_pred, protected_test.reset_index(drop=True)
        )

        # --- Drift metrics ---
        drift_metrics, X_drifted = simulate_drift(X_train_raw, X_test)

        # --- Plots ---
        run_dir = f"mlflow_artifacts/{model_name.replace(' ', '_')}"
        cm_path, drift_path, bias_path = make_plots(
            y_test, y_pred, X_train_raw, X_drifted,
            X_train.columns.tolist(), protected_test.reset_index(drop=True), run_dir
        )

        # --- Log everything to MLflow ---
        mlflow.log_params({
            "model_type": model_name,
            "train_size": len(X_train),
            "test_size": len(X_test),
            "n_features": X_train.shape[1],
        })

        mlflow.log_metrics({"accuracy": acc, "f1_score": f1, "roc_auc": auc})
        mlflow.log_metrics(dq_metrics)
        mlflow.log_metrics(bias_metrics)
        mlflow.log_metrics(drift_metrics)

        mlflow.log_artifact(cm_path)
        mlflow.log_artifact(drift_path)
        mlflow.log_artifact(bias_path)

        # FIX: Define unique artifact path paths & Register models cleanly matching UI naming conventions
        artifact_path = f"model_components_{model_name.lower().replace(' ', '_')}"
        registered_model_name = f"Adult_Income_{model_name.replace(' ', '_')}"

        mlflow.sklearn.log_model(
            sk_model=model,
            artifact_path=artifact_path,
            registered_model_name=registered_model_name
        )

        run_id = mlflow.active_run().info.run_id
        print(f"   ✅ Logged to MLflow | Run ID: {run_id[:8]}...")

        return acc, f1, auc


# ─────────────────────────────────────────────
# 8. ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":

    # FIX: Point explicitly to your active local server container instance
    mlflow.set_tracking_uri("http://127.0.0.1:5000")

    # Setup MLflow experiment 
    mlflow.set_experiment("Bias_Drift_DataQuality_Monitor")

    # Load & check data
    df = load_adult_data()
    dq_metrics = check_data_quality(df)

    # Preprocess
    X, y, protected, feature_cols = preprocess(df)
    X_train, X_test, y_train, y_test, prot_train, prot_test = train_test_split(
        X, y, protected, test_size=0.2, random_state=42, stratify=y
    )

    # Scale
    scaler = StandardScaler()
    X_train_sc = pd.DataFrame(scaler.fit_transform(X_train), columns=feature_cols)
    X_test_sc  = pd.DataFrame(scaler.transform(X_test),      columns=feature_cols)

    # Models to compare
    models = {
        "Logistic Regression": LogisticRegression(max_iter=500, random_state=42),
        "Gradient Boosting":   GradientBoostingClassifier(n_estimators=150, max_depth=4,
                                                          learning_rate=0.1, random_state=42),
    }

    print("\n" + "="*60)
    print("  MLflow Experiment: Bias + Drift + Data Quality")
    print("="*60)

    results = {}
    for name, model in models.items():
        acc, f1, auc = train_and_log(
            name, model,
            X_train_sc, X_test_sc,
            y_train, y_test,
            prot_test, dq_metrics, X_train
        )
        results[name] = {"accuracy": acc, "f1": f1, "auc": auc}

    # Summary
    print("\n" + "="*60)
    print("  FINAL RESULTS SUMMARY")
    print("="*60)
    for name, r in results.items():
        print(f"  {name:<25} Acc={r['accuracy']:.4f}  F1={r['f1']:.4f}  AUC={r['auc']:.4f}")

    print("\n✅ Done! Check your local browser dashboard:")
    print("   → http://localhost:5000")
    print('   → New Experiment: "Bias_Drift_DataQuality_Monitor"')