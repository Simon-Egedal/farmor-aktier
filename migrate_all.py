#!/usr/bin/env python3
"""Migrate all collections to add username field"""

from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()
CONNECTION_STRING = os.getenv("MONGODB_CONNECTION_STRING")

client = MongoClient(CONNECTION_STRING, serverSelectionTimeoutMS=15000)
db = client["stock_portfolio"]

print("[DEBUG] Migrating all collections...\n")

# Migrate transactions
print("=== TRANSACTIONS ===")
transactions = db["transactions"]
without_username = transactions.count_documents({"username": {"$exists": False}})
print(f"Documents without username: {without_username}")

if without_username > 0:
    result = transactions.update_many(
        {"username": {"$exists": False}},
        {"$set": {"username": "simon"}}
    )
    print(f"[✓] Updated {result.modified_count} documents")

# Note: cash and dividends are global (not per-user), but we can add username if needed
print("\n=== CASH (global) ===")
cash = db["cash"]
cash_docs = cash.count_documents({})
print(f"Total cash documents: {cash_docs}")

print("\n[✓] Migration complete!")
