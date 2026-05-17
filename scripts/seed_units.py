#!/usr/bin/env python3
"""
Seed aria-units and aria-hospitals DynamoDB tables with mock data for demo.

Usage:
    python scripts/seed_units.py
    python scripts/seed_units.py --reset   # clears existing items first
"""
import argparse
import boto3
import json
import sys

REGION = "us-east-1"
dynamodb = boto3.resource("dynamodb", region_name=REGION)

MOCK_UNITS = [
    {"unit_id": "AMB-001", "unit_type": "ambulance", "status": "available", "lat": 37.7749, "lng": -122.4194, "current_assignment": None, "als_capable": True},
    {"unit_id": "AMB-002", "unit_type": "ambulance", "status": "available", "lat": 37.7808, "lng": -122.4104, "current_assignment": None, "als_capable": True},
    {"unit_id": "AMB-003", "unit_type": "ambulance", "status": "available", "lat": 37.7688, "lng": -122.4286, "current_assignment": None, "als_capable": False},
    {"unit_id": "FIRE-001", "unit_type": "fire_engine", "status": "available", "lat": 37.7751, "lng": -122.4308, "current_assignment": None, "station": "Station 3"},
    {"unit_id": "FIRE-002", "unit_type": "fire_engine", "status": "available", "lat": 37.7879, "lng": -122.4162, "current_assignment": None, "station": "Station 7"},
    {"unit_id": "POL-001", "unit_type": "police", "status": "available", "lat": 37.7652, "lng": -122.4195, "current_assignment": None, "district": "Mission"},
    {"unit_id": "POL-002", "unit_type": "police", "status": "available", "lat": 37.7812, "lng": -122.4080, "current_assignment": None, "district": "SoMa"},
    {"unit_id": "HAZ-001", "unit_type": "hazmat", "status": "available", "lat": 37.7738, "lng": -122.3970, "current_assignment": None, "certification": "Level A"},
    {"unit_id": "LAD-001", "unit_type": "ladder", "status": "available", "lat": 37.7776, "lng": -122.4227, "current_assignment": None, "height_ft": 100},
    {"unit_id": "SUP-001", "unit_type": "supervisor", "status": "available", "lat": 37.7760, "lng": -122.4150, "current_assignment": None, "rank": "Battalion Chief"},
]

MOCK_HOSPITALS = [
    {
        "hospital_id": "H001", "region": "us-east-1",
        "name": "UCSF Medical Center", "lat": 37.7631, "lng": -122.4578,
        "capabilities": ["trauma_bay", "icu", "burn_unit", "cardiac_cath"],
        "trauma_level": 1, "er_status": "accepting",
        "current_capacity": 3, "max_capacity": 10, "distance_minutes": 6,
    },
    {
        "hospital_id": "H002", "region": "us-east-1",
        "name": "SF General Hospital", "lat": 37.7554, "lng": -122.4059,
        "capabilities": ["trauma_bay", "icu", "psychiatric"],
        "trauma_level": 1, "er_status": "accepting",
        "current_capacity": 5, "max_capacity": 12, "distance_minutes": 8,
    },
    {
        "hospital_id": "H003", "region": "us-east-1",
        "name": "St. Mary's Medical Center", "lat": 37.7792, "lng": -122.4473,
        "capabilities": ["trauma_bay", "cardiac_cath"],
        "trauma_level": 2, "er_status": "accepting",
        "current_capacity": 2, "max_capacity": 8, "distance_minutes": 9,
    },
    {
        "hospital_id": "H004", "region": "us-east-1",
        "name": "California Pacific Medical Center", "lat": 37.7906, "lng": -122.4271,
        "capabilities": ["trauma_bay", "icu", "neonatal"],
        "trauma_level": 2, "er_status": "accepting",
        "current_capacity": 4, "max_capacity": 10, "distance_minutes": 11,
    },
    {
        "hospital_id": "H005", "region": "us-east-1",
        "name": "Zuckerberg SF General Trauma Center", "lat": 37.7556, "lng": -122.4058,
        "capabilities": ["trauma_bay", "icu", "burn_unit", "pediatric_er"],
        "trauma_level": 1, "er_status": "accepting",
        "current_capacity": 6, "max_capacity": 15, "distance_minutes": 7,
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

    print(f"Seeding {len(MOCK_UNITS)} units...")
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

    print(f"Seeding {len(MOCK_HOSPITALS)} hospitals...")
    with table.batch_writer() as batch:
        for hospital in MOCK_HOSPITALS:
            batch.put_item(Item=hospital)
    print(f"  ✓ {len(MOCK_HOSPITALS)} hospitals seeded into aria-hospitals")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed ARIA mock data")
    parser.add_argument("--reset", action="store_true", help="Clear existing items before seeding")
    args = parser.parse_args()

    try:
        seed_units(reset=args.reset)
        seed_hospitals(reset=args.reset)
        print("\nSeed complete. Run 'aws dynamodb scan --table-name aria-units' to verify.")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
