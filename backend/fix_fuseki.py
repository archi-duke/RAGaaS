from app.core.fuseki import fuseki_client
import sys

KB_ID = "171dbd5b-c42d-4cd5-8bb7-ea2044060aed"

print(f"Creating Fuseki dataset for {KB_ID}...")
success = fuseki_client.create_dataset(KB_ID)

if success:
    print("✅ Dataset created successfully.")
else:
    print("❌ Failed to create dataset.")
