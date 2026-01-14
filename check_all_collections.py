#!/usr/bin/env python3
"""Check all collections in the database"""

from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()
CONNECTION_STRING = os.getenv("MONGODB_CONNECTION_STRING")

client = MongoClient(CONNECTION_STRING, serverSelectionTimeoutMS=15000)
db = client["stock_portfolio"]

print("Collections in database:")
for collection_name in db.list_collection_names():
    print(f"\n=== {collection_name} ===")
    collection = db[collection_name]
    count = collection.count_documents({})
    print(f"Total documents: {count}")
    
    if count > 0:
        docs = list(collection.find().limit(5))
        for i, doc in enumerate(docs, 1):
            print(f"\nDocument {i}:")
            for key, value in doc.items():
                if key != '_id':
                    print(f"  {key}: {value}")
