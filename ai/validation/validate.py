import pandas as pd 
import numpy as np 
import seaborn as sns 
from scipy import stats
import matplotlib.pyplot as plt

print("All libraries imported")


edu_dataset = pd.read_csv("../Dataset/edushield_phone_change_dataset.csv")
print("CSV file loaded")

edu = pd.DataFrame(edu_dataset) #prints the dataset in a tabular format
#print(edu)

#Print the first 10 rows 
print(edu.head(10))

#Number of rows and columns in the dataset
print(edu.shape)

#Column names in the dataset
print(edu.columns)

#Missing values in the dataset 
print("Missing values in the dataset:")
print(edu.isnull().sum()) #The dataset has no missing values
print()
#Check for NaN values in the dataset
print("NaN values in the dataset:")
print(edu.isna().sum()) #The dataset has no NaN values
print()

#Check for empty strings 
print("Empty strings in the dataset:")
print(edu.eq('').sum()) #The dataset has no empty strings
print()

#Code issues detected here
#Check for the infinite values 
#print("Infinite values in the dataset:")
#infiite_value = np.isinf(edu).any().any()
#print(infiite_value) #The dataset has no infinite values

#Check for invalid data types in the dataset
print("Invalid data types in the dataset:")
edu.info()

#Range validation for numerical columns
print("Range validation for numerical columns:")
#known_device should be between 0 and 1
invalid_known_device = edu[(edu['known_device'] < 0) | (edu['known_device'] > 1)]
if not invalid_known_device.empty:
    print("Invalid known_device values found:")
    print(invalid_known_device)
else:
    print("All values in known_device column are within the valid range (0 to 1).")

#location should be between 0 and 1
invalid_location = edu[(edu['location_deviation'] < 0) | (edu['location_deviation'] > 1)]
if not invalid_location.empty:
    print("Invalid location values found:")
    print(invalid_location)
else:
    print("All values in location_deviation column are within the valid range (0 to 1).")

#Trust score should be between 0 and 100
invalid_trust_score = edu[(edu['trust_score'] < 0) | (edu['trust_score'] > 100)]
if not invalid_trust_score.empty:
    print("Invalid trust_score values found:")
    print(invalid_trust_score)
else:
    print("All values in trust_score column are within the valid range (0 to 100).")

#Count the fetures in the dataset
#failed_login_count should be between >=0
invalid_failed_login_count = edu[edu['failed_login_count'] < 0]
if not invalid_failed_login_count.empty:
    print("Invalid failed_login_count values found:")
    print(invalid_failed_login_count)
else:
    print("All values in failed_login_count column are within the valid range (>=0).")

#phone_change_count should be between >=0
invalid_phone_change_count = edu[edu['phone_change_frequency'] < 0]
if not invalid_phone_change_count.empty:
    print("Invalid phone_change_count values found:")
    print(invalid_phone_change_count)
else:
    print("All values in phone_change_count column are within the valid range (>=0).")
print()
#Class detection
#check label==1 and label==0
#number of legit requests (label==0)
legit_requests = edu[edu['label'] == 0] 
print(f"Number of legit requests:: {len(legit_requests)}")

#number of fraudulent requests (label==1)
fraudulent_requests = edu[edu['label'] == 1]
print(f"Number of fraudulent requests:: {len(fraudulent_requests)}")

#Percentage of legit requests
legit_percentage = (len(legit_requests) / len(edu)) * 100
print(f"Percentage of legit requests: {legit_percentage:.2f}%")

#Percentage of fraudulent requests
fraudulent_percentage = (len(fraudulent_requests) / len(edu)) * 100
print(f"Percentage of fraudulent requests: {fraudulent_percentage:.2f}%")   
print()
#Numerical Feature Statistics
print("Numerical Feature Statistics:")

#min, max, mean, median, std for numerical features
numerical_features = [ 'location_deviation', 'trust_score', 'failed_login_count', 'phone_change_frequency']
for feature in numerical_features:
    min_value = edu[feature].min()
    max_value = edu[feature].max()
    mean_value = edu[feature].mean()
    median_value = edu[feature].median()
    std_value = edu[feature].std()
    
    print(f"{feature}:")
    print(f"  Min: {min_value}")
    print(f"  Max: {max_value}")
    print(f"  Mean: {mean_value}")
    print(f"  Median: {median_value}")
    print(f"  Std: {std_value}")
    print()

#Standard Deviation and Variance for numerical features
print("Standard Deviation and Variance for numerical features:")

for feature in numerical_features:
    std_value = edu[feature].std()
    var_value = edu[feature].var()
    
    print(f"{feature}:")
    print(f"  Std: {std_value}")
    print(f"  Variance: {var_value}")
    print()

#Outlier detection using Z-score method
print("Outlier detection using Z-score method:")


for feature in numerical_features:
    z_scores = stats.zscore(edu[feature])
    outliers = edu[abs(z_scores) > 3]
    print(f"{feature}: {len(outliers)} outliers found")

#Keeping existing outliners to make sure the model is trained on all the data and can learn from the outliers as well.
#Also since its a fraud detection model , we want it to detect annomalies and outliers in data

#Check for duplicate rows in the dataset
duplicate_rows = edu[edu.duplicated()]
print(f"Number of duplicate rows in the dataset: {len(duplicate_rows)}") #0 duplicates 

#Check duplicates based on event_id and user_id
duplicate_event_user = edu[edu.duplicated(subset=['event_id', 'user_id'])]
print(f"Number of duplicate rows based on event_id and user_id: {len(duplicate_event_user)}") #0 duplicates


#Feature vs label analysis
print("Feature vs Label Analysis:")
legitimate = edu[edu["label"] == 0]
suspicious = edu[edu["label"] == 1]

for feature in numerical_features:
    legit_mean = legitimate[feature].mean()
    suspicious_mean = suspicious[feature].mean()
    
    print(f"{feature}:")
    print(f"  Mean for legitimate requests: {legit_mean:.2f}")
    print(f"  Mean for suspicious requests: {suspicious_mean:.2f}")
    print()

#For binary features 
binary_feature = ['known_device','recent_password_reset','mfa_verified']

for feature in binary_feature:
    legit_count = legitimate[feature].mean()
    suspicious_count = suspicious[feature].mean()
    
    print(f"{feature}:")
    print(f"  Legitimate requests count:\n{legit_count:.2f}")
    print(f"  Suspicious requests count:\n{suspicious_count:.2f}")
    print()

#Presenting the findings
features = numerical_features + binary_feature
comparison = edu.groupby("label")[features].mean().T
comparison.columns = ["Legitimate", "Suspicious"]

print(comparison)

#Leakage check
#A leakage is basically checking if we are giving the moodel any inormation 
#that already revelas the answer to the question we are trying to answer 
#In this case it is fraud detection


#None of these features should be used to train the model 
#Because they are either identifiers or the target variable itself
excluded = [
    "event_id",
    "user_id",
    "label"
]

features = [c for c in edu.columns if c not in excluded]

print("Features used by model:")
print(features)

print(edu.corr(numeric_only=True)["label"].sort_values(ascending=False))
corr = edu.corr(numeric_only=True)

#HeatMap of the correlation matrix
plt.figure(figsize=(10, 8))
plt.imshow(corr, cmap="coolwarm")
plt.colorbar()
plt.xticks(range(len(corr.columns)), corr.columns, rotation=90)
plt.yticks(range(len(corr.columns)), corr.columns)
plt.title("Feature Correlation Matrix")
plt.tight_layout()
plt.show()
#******ML Model Features******
#known_device
#location_deviation
#failed_login_count
#recent_password_reset
#mfa_verified
#phone_change_frequency
#login_time_deviation
#trust_score

user_counts = edu["user_id"].value_counts()

print("Unique users:", edu["user_id"].nunique())
print("Average events/user:", user_counts.mean())
print("Maximum events/user:", user_counts.max())
print("Minimum events/user:", user_counts.min())

print("Users with 1 event:", (user_counts == 1).sum())
print("Users with 2+ events:", (user_counts >= 2).sum())
print("Maximum events by one user:", user_counts.max())

#Check the cross tab 
print(pd.crosstab(edu["recent_password_reset"], edu["label"], normalize="index"))

print(pd.crosstab(edu["mfa_verified"], edu["label"], normalize="index"))

print()

#Scenario Analysis
scenarios = {
    "Legitimate New Device": (
        (edu["known_device"] == 0) &
        (edu["mfa_verified"] == 1) &
        (edu["trust_score"] >= 60) &
        (edu["failed_login_count"] <= 1)
    ),

    "Suspicious New Device": (
        (edu["known_device"] == 0) &
        (edu["location_deviation"] >= 0.6) &
        (edu["failed_login_count"] >= 2)
    ),

    "Recent Password Reset": (
        (edu["recent_password_reset"] == 1) &
        (edu["mfa_verified"] == 1)
    ),

    "Repeated Phone Changes": (
        edu["phone_change_frequency"] >= 2
    ),

    "High Risk Combination": (
        (edu["known_device"] == 0) &
        (edu["location_deviation"] >= 0.6) &
        (edu["failed_login_count"] >= 2) &
        (edu["recent_password_reset"] == 1) &
        (edu["trust_score"] <= 40)
    )
}

for name, condition in scenarios.items():
    print(f"{name}: {condition.sum()} records")