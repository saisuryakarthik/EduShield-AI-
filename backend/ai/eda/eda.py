#This python file aims to do a EDA of the validated dataset 
import pandas as pd
import numpy as np 
import matplotlib.pyplot as plt
import seaborn as sns

#Loading the dataset 
edu = pd.read_csv("EduShield-AI-\Dataset\edushield_phone_change_dataset.csv")
print("CSV file loaded")
print(f"Shape of the dataset: {edu.shape}")

#Class distribution
label_counts = edu['label'].value_counts()
print("Class distribution:")
print(label_counts)

#percentage distribution of classes
print(edu["label"].value_counts(normalize=True) * 100)
print("Percentage distribution of classes:")

#EDA Graphs
plt.figure(figsize=(6, 4))

sns.countplot(
    data=edu,
    x="label"
)

plt.title("Phone Number Change Request Distribution")
plt.xlabel("Request Type (0 = Legitimate, 1 = Suspicious)")
plt.ylabel("Number of Requests")

plt.show()

#feature distribution for known_device
plt.figure(figsize=(6, 4))
sns.histplot(
    data=edu,
    x="known_device",
    bins=10,
    kde=True
)
plt.title("Distribution of Known Device Feature")
plt.xlabel("Known Device (0 = Unknown, 1 = Known)")
plt.ylabel("Frequency")
plt.show()

plt.figure(figsize=(8, 5))

sns.histplot(
    data=edu,
    x="trust_score",
    hue="label",
    kde=True,
    bins=20
)

plt.title("Trust Score Distribution")
plt.xlabel("Trust Score")
plt.ylabel("Frequency")

plt.show()

#location deviation
plt.figure(figsize=(8, 5))

sns.histplot(
    data=edu,
    x="location_deviation",
    hue="label",
    kde=True,
    bins=20
)

plt.title("Location Deviation by Request Type")
plt.xlabel("Location Deviation")
plt.ylabel("Frequency")

plt.show()

#failed login count
plt.figure(figsize=(8, 5))

sns.histplot(
    data=edu,
    x="failed_login_count",
    hue="label",
    kde=True,
    bins=15
)

plt.title("Failed Login Attempts by Request Type")
plt.xlabel("Recent Failed Login Count")
plt.ylabel("Frequency")

plt.show()

#phone number change frequency
plt.figure(figsize=(8, 5))

sns.histplot(
    data=edu,
    x="phone_change_frequency",
    hue="label",
    kde=True,
    bins=15
)

plt.title("Phone Number Change Frequency")
plt.xlabel("Previous Phone Change Requests")
plt.ylabel("Frequency")

plt.show()

#login time deviation
plt.figure(figsize=(8, 5))

sns.histplot(
    data=edu,
    x="login_time_deviation",
    hue="label",
    kde=True,
    bins=20
)

plt.title("Login Time Deviation")
plt.xlabel("Login Time Deviation")
plt.ylabel("Frequency")

plt.show()

print("EDA completed successfully.")


#Final checks 
#feature distrution and skewness 
print("\n[9] SKEWNESS")

features = [
    "location_deviation",
    "failed_login_count",
    "phone_change_frequency",
    "login_time_deviation",
    "trust_score"
]

print(edu[features].skew().round(3))


#feature to feature correlation
corr = edu[features].corr()

for i in range(len(corr.columns)):
    for j in range(i + 1, len(corr.columns)):
        value = corr.iloc[i, j]

        if abs(value) >= 0.70:
            print(
                f"{corr.columns[i]} ↔ {corr.columns[j]}: "
                f"{value:.3f}"
            )

        