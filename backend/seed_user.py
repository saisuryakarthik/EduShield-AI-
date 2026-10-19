import mysql.connector
from config import DB_CONFIG
from auth import hash_password

connection = mysql.connector.connect(**DB_CONFIG)
cursor = connection.cursor()

cursor.execute(
    """UPDATE users SET role = %s, password_hash = %s WHERE user_id = %s""",
    ("student", hash_password("test1234"), "S1024")
)

connection.commit()
cursor.close()
connection.close()
print("Done — S1024 now has role=student, password=test1234")



connection = mysql.connector.connect(**DB_CONFIG)
cursor = connection.cursor()

cursor.execute(
    """UPDATE users SET role = %s, password_hash = %s WHERE user_id = %s""",
    ("student", hash_password("test1234"), "S1024")
)

cursor.execute(
    """UPDATE users SET password_hash = %s WHERE user_id = %s""",
    (hash_password("mentor1234"), "M021")
)

connection.commit()
cursor.close()
connection.close()
print("Done — S1024 (student) and M021 (mentor) passwords set")