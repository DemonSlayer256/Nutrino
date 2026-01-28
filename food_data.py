import firebase_admin
from firebase_admin import credentials, firestore
import json
import re

# Initialize Firebase
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Load JSON data
with open('food_data.json', 'r') as f:
    data = json.load(f)

def generate_search_keywords(food_name):
    """
    Generate simple search keywords:
    - Split words
    - Add prefixes for autocomplete
    """
    food_name = food_name.lower()
    words = re.findall(r'\w+', food_name)  # split into words
    keywords = set()

    for word in words:
        # Add full word
        keywords.add(word)
        # Add prefixes for autocomplete
        for i in range(1, len(word) + 1):
            keywords.add(word[:i])

    return list(keywords)

# Create batch
batch = db.batch()
collection_ref = db.collection('food_data')

for doc in data:
    food_code = doc.pop('food_code')  # Remove food_code from doc

    # Generate search keywords
    food_name = doc.get('food_name', '')
    doc['search_keywords'] = generate_search_keywords(food_name)

    doc_ref = collection_ref.document(food_code)
    batch.set(doc_ref, doc)

# Commit batch
batch.commit()
print("Data imported successfully with search keywords!")
