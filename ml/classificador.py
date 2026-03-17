import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
import joblib
import os

DATASET_PATH = "dataset/files_dataset.csv"
MODEL_PATH = "ml/model.pkl"


def load_dataset():

    if not os.path.exists(DATASET_PATH):
        print("Dataset não encontrado.")
        return None

    df = pd.read_csv(DATASET_PATH)

    return df


def prepare_features(df):

    # colunas usadas como features
    features = [
        "size_kb",
        "days_since_modified",
        "important_keyword"
    ]

    X = df[features]

    # alvo: arquivo importante ou não
    if "important" not in df.columns:
        print("Coluna 'important' não encontrada no dataset")
        return None, None

    y = df["important"]

    return X, y


def train_model():

    df = load_dataset()

    if df is None:
        return

    X, y = prepare_features(df)

    if X is None:
        return

    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=0.2,
        random_state=42
    )

    model = RandomForestClassifier(
        n_estimators=100,
        random_state=42
    )

    model.fit(X_train, y_train)

    predictions = model.predict(X_test)

    print("\nRelatório de classificação:\n")
    print(classification_report(y_test, predictions))

    joblib.dump(model, MODEL_PATH)

    print("\nModelo salvo em:", MODEL_PATH)


def load_model():

    if not os.path.exists(MODEL_PATH):
        print("Modelo ainda não treinado.")
        return None

    model = joblib.load(MODEL_PATH)

    return model


def predict_file(file_features):

    model = load_model()

    if model is None:
        return None

    df = pd.DataFrame([file_features])

    prediction = model.predict(df)

    return prediction[0]