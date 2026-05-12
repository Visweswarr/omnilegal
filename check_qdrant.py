import requests
import json

def check_qdrant():
    try:
        base_url = "http://localhost:6333"
        response = requests.get(f"{base_url}/collections")
        data = response.json()
        
        collections = data.get("result", {}).get("collections", [])
        print(f"Found {len(collections)} collections in Qdrant:")
        
        total_points = 0
        for col in collections:
            name = col["name"]
            try:
                count_response = requests.get(f"{base_url}/collections/{name}")
                count_data = count_response.json()
                points_count = count_data.get("result", {}).get("points_count", 0)
                total_points += points_count
                if points_count > 0:
                    print(f" - {name}: {points_count} points")
            except Exception as e:
                print(f" - {name}: Error fetching count ({e})")
                
        print(f"\nTotal points across all collections: {total_points}")
    except Exception as e:
        print(f"Failed to connect to Qdrant at {base_url}: {e}")

if __name__ == "__main__":
    check_qdrant()
