import pandas as pd

#load the dataset 
edu =  pd.read_csv("C:\\Users\\Surya\\EduShield Ai\\EduShield-AI-\\Dataset\\edushield_phone_change_dataset.csv")

#Target variable
TARGET = 'label'

#Features used by the ML model
FEATURES = [
    "known_device",
    "location_deviation",
    "failed_login_count",
    "recent_password_reset",
    "mfa_verified",
    "phone_change_frequency",
    "login_time_deviation",
    "trust_score"
]
#Create a Feature and a target matrix
x = edu[FEATURES].copy()
y = edu[TARGET].copy()

print("Features used by model:")
for feature in FEATURES:
    print(f"- {feature}")


print(f"\nNumber of samples: {len(x)}")
print(f"Number of features: {x.shape[1]}")

print("\nFeature Data Types:")
print(x.dtypes)

print("\nTarget Distribution:")
print(y.value_counts())

print("\nFeature Matrix:")
print(x.head())

print("\nTarget:")
print(y.head())

print("\nFeature engineering complete.")