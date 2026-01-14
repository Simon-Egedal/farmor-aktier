#!/usr/bin/env python3
"""Migrate portfolio data to add username field"""

from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()
CONNECTION_STRING = os.getenv("MONGODB_CONNECTION_STRING")

client = MongoClient(CONNECTION_STRING, serverSelectionTimeoutMS=15000)
db = client["stock_portfolio"]
portfolio = db["portfolio"]

print("[DEBUG] Checking portfolio collection...")
print(f"Total documents: {portfolio.count_documents({})}")

# Check if any documents have username
with_username = portfolio.count_documents({"username": {"$exists": True}})
without_username = portfolio.count_documents({"username": {"$exists": False}})

print(f"Documents with username: {with_username}")
print(f"Documents without username: {without_username}")

if without_username > 0:
    print("\n[MIGRATING] Adding username field to documents...")
    
    # Get all documents without username
    docs = list(portfolio.find({"username": {"$exists": False}}))
    print(f"Found {len(docs)} documents to migrate")
    
    # Show first few before migration
    print("\nSample documents before migration:")
    for doc in docs[:2]:
        print(f"  _id: {doc['_id']}, ticker: {doc.get('ticker')}, username: {doc.get('username', 'MISSING')}")
    
    # Update all documents to add username = "simon" (default user)
    result = portfolio.update_many(
        {"username": {"$exists": False}},
        {"$set": {"username": "simon"}}
    )
    
    print(f"\n[✓] Updated {result.modified_count} documents")
    
    # Verify migration
    with_username = portfolio.count_documents({"username": {"$exists": True}})
    print(f"After migration - Documents with username: {with_username}")
    
    # Show sample after migration
    print("\nSample documents after migration:")
    for doc in portfolio.find({"username": "simon"}).limit(2):
        print(f"  ticker: {doc.get('ticker')}, username: {doc.get('username')}, shares: {doc.get('shares')}")
else:
    print("\n[✓] All documents already have username field")
