#!/usr/bin/env python3
"""
Seed aria-units and aria-hospitals DynamoDB tables with Seattle / King County mock data.

Usage:
    python scripts/seed_units.py
    python scripts/seed_units.py --reset   # clears existing items first
"""
import argparse
import boto3
import sys

REGION = "us-east-1"
dynamodb = boto3.resource("dynamodb", region_name=REGION)

# Seattle / King County area units (lat/lng are real Seattle neighborhoods)
MOCK_UNITS = [
    # Ambulances — King County Medic One
    {"unit_id": "MED-1", "unit_type": "ambulance", "status": "available",
     "lat": 47.6027, "lng": -122.3321, "current_assignment": None, "als_capable": True,
     "station": "Station 10 — SoDo"},
    {"unit_id": "MED-2", "unit_type": "ambulance", "status": "available",
     "lat": 47.6205, "lng": -122.3493, "current_assignment": None, "als_capable": True,
     "station": "Station 2 — Belltown"},
    {"unit_id": "MED-3", "unit_type": "ambulance", "status": "available",
     "lat": 47.6588, "lng": -122.3130, "current_assignment": None, "als_capable": False,
     "station": "Station 18 — University District"},
    # Fire Engines — Seattle Fire Department
    {"unit_id": "FIRE-1", "unit_type": "fire_engine", "status": "available",
     "lat": 47.6038, "lng": -122.3301, "current_assignment": None,
     "station": "Station 10 — SoDo"},
    {"unit_id": "FIRE-2", "unit_type": "fire_engine", "status": "available",
     "lat": 47.6148, "lng": -122.3426, "current_assignment": None,
     "station": "Station 5 — Lake Union"},
    # Police — Seattle PD
    {"unit_id": "POL-1", "unit_type": "police", "status": "available",
     "lat": 47.6062, "lng": -122.3321, "current_assignment": None,
     "district": "West Precinct — Downtown"},
    {"unit_id": "POL-2", "unit_type": "police", "status": "available",
     "lat": 47.6221, "lng": -122.3219, "current_assignment": None,
     "district": "East Precinct — Capitol Hill"},
    # Hazmat — Seattle Fire Hazmat
    {"unit_id": "HAZ-1", "unit_type": "hazmat", "status": "available",
     "lat": 47.5951, "lng": -122.3188, "current_assignment": None,
     "certification": "Level A", "station": "Station 28 — Georgetown"},
    # Ladder Truck
    {"unit_id": "LAD-1", "unit_type": "ladder", "status": "available",
     "lat": 47.6062, "lng": -122.3310, "current_assignment": None,
     "height_ft": 100, "station": "Station 10 — SoDo"},
    # Supervisor / Battalion Chief
    {"unit_id": "BC-1", "unit_type": "supervisor", "status": "available",
     "lat": 47.6090, "lng": -122.3380, "current_assignment": None,
     "rank": "Battalion Chief", "district": "Battalion 1 — Downtown"},
]

# Seattle / King County hospitals
MOCK_HOSPITALS = [
    {
        "hospital_id": "H001", "region": "us-east-1",
        "name": "Harborview Medical Center",
        "address": "325 9th Ave, Seattle, WA 98104",
        "lat": 47.6027, "lng": -122.3209,
        "capabilities": ["trauma_bay", "icu", "burn_unit", "cardiac_cath",
                         "stroke_team", "psychiatric", "spinal"],
        "trauma_level": 1, "er_status": "accepting",
        "current_capacity": 3, "max_capacity": 10, "distance_minutes": 5,
        "notes": "Only Level 1 trauma center in Pacific Northwest. Only burn center in WA.",
    },
    {
        "hospital_id": "H002", "region": "us-east-1",
        "name": "UW Medical Center",
        "address": "1959 NE Pacific St, Seattle, WA 98195",
        "lat": 47.6498, "lng": -122.3072,
        "capabilities": ["trauma_bay", "icu", "cardiac_cath", "stroke_team", "neonatal"],
        "trauma_level": 2, "er_status": "accepting",
        "current_capacity": 4, "max_capacity": 8, "distance_minutes": 10,
        "notes": "Primary overflow for Harborview. Strong cardiac and neuro. NICU.",
    },
    {
        "hospital_id": "H003", "region": "us-east-1",
        "name": "Swedish Medical Center — First Hill",
        "address": "747 Broadway, Seattle, WA 98122",
        "lat": 47.6085, "lng": -122.3218,
        "capabilities": ["trauma_bay", "icu", "cardiac_cath", "stroke_team", "neonatal"],
        "trauma_level": 2, "er_status": "accepting",
        "current_capacity": 2, "max_capacity": 6, "distance_minutes": 6,
        "notes": "Strong cardiac program. Stroke team 24/7. Close to downtown.",
    },
    {
        "hospital_id": "H004", "region": "us-east-1",
        "name": "Seattle Children's Hospital",
        "address": "4800 Sand Point Way NE, Seattle, WA 98105",
        "lat": 47.6632, "lng": -122.2973,
        "capabilities": ["pediatric_er", "pediatric_icu", "neonatal",
                         "pediatric_trauma", "pediatric_burn"],
        "trauma_level": 1, "er_status": "accepting",
        "current_capacity": 2, "max_capacity": 8, "distance_minutes": 15,
        "notes": "All pediatric emergencies. Level 1 pediatric trauma.",
    },
    {
        "hospital_id": "H005", "region": "us-east-1",
        "name": "Overlake Medical Center",
        "address": "1035 116th Ave NE, Bellevue, WA 98004",
        "lat": 47.6138, "lng": -122.1969,
        "capabilities": ["trauma_bay", "icu", "cardiac_cath", "stroke_team"],
        "trauma_level": 3, "er_status": "accepting",
        "current_capacity": 3, "max_capacity": 8, "distance_minutes": 20,
        "notes": "Primary hospital for Eastside. Level 3 — stabilize and transfer for complex trauma.",
    },
]


def seed_units(reset: bool = False) -> None:
    table = dynamodb.Table("aria-units")
    if reset:
        print("Clearing existing unit records...")
        existing = table.scan().get("Items", [])
        with table.batch_writer() as batch:
            for item in existing:
                batch.delete_item(Key={"unit_id": item["unit_id"], "status": item["status"]})

    print(f"Seeding {len(MOCK_UNITS)} units (Seattle / King County)...")
    with table.batch_writer() as batch:
        for unit in MOCK_UNITS:
            batch.put_item(Item=unit)
    print(f"  ✓ {len(MOCK_UNITS)} units seeded into aria-units")


def seed_hospitals(reset: bool = False) -> None:
    table = dynamodb.Table("aria-hospitals")
    if reset:
        print("Clearing existing hospital records...")
        existing = table.scan().get("Items", [])
        with table.batch_writer() as batch:
            for item in existing:
                batch.delete_item(Key={"hospital_id": item["hospital_id"], "region": item["region"]})

    print(f"Seeding {len(MOCK_HOSPITALS)} hospitals (Seattle / King County)...")
    with table.batch_writer() as batch:
        for hospital in MOCK_HOSPITALS:
            batch.put_item(Item=hospital)
    print(f"  ✓ {len(MOCK_HOSPITALS)} hospitals seeded into aria-hospitals")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed ARIA mock data — Seattle / King County")
    parser.add_argument("--reset", action="store_true", help="Clear existing items before seeding")
    args = parser.parse_args()

    try:
        seed_units(reset=args.reset)
        seed_hospitals(reset=args.reset)
        print("\nSeed complete. Run 'aws dynamodb scan --table-name aria-units' to verify.")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
