#!/usr/bin/env python3
"""
Generate Test Data - Create sample Excel and CSV files for testing.

This script creates test fixtures in the test_data/ directory.
"""

import csv
import os
from pathlib import Path

from openpyxl import Workbook


# Test data directory
TEST_DATA_DIR = Path(__file__).parent.parent / "test_data"


def create_test_data_dir() -> None:
    """Create test_data directory if it doesn't exist."""
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Test data directory: {TEST_DATA_DIR}")


def create_valid_recipes_xlsx() -> None:
    """Create sample_recipes.xlsx with 10 valid recipes."""
    filepath = TEST_DATA_DIR / "sample_recipes.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Recipes"

    # Headers
    headers = ["Recipe Name", "Category", "Prep Time (min)", "Servings", "Ingredients", "Instructions"]
    ws.append(headers)

    # 10 sample recipes
    recipes = [
        ["Spaghetti Carbonara", "Italian", 30, 4, "Pasta, eggs, bacon, parmesan", "Cook pasta, mix with egg mixture and bacon"],
        ["Chicken Tikka Masala", "Indian", 45, 6, "Chicken, tomatoes, cream, spices", "Marinate chicken, grill, simmer in sauce"],
        ["Caesar Salad", "American", 15, 2, "Romaine, croutons, parmesan, dressing", "Toss lettuce with dressing and toppings"],
        ["Beef Tacos", "Mexican", 25, 4, "Ground beef, tortillas, toppings", "Brown beef, assemble tacos with toppings"],
        ["Pad Thai", "Thai", 35, 3, "Rice noodles, shrimp, peanuts, sauce", "Stir-fry noodles with shrimp and sauce"],
        ["French Onion Soup", "French", 60, 4, "Onions, beef broth, bread, cheese", "Caramelize onions, add broth, top with cheese"],
        ["Greek Salad", "Greek", 10, 4, "Cucumber, tomato, feta, olives", "Chop vegetables, add cheese and dressing"],
        ["Butter Chicken", "Indian", 40, 5, "Chicken, butter, tomatoes, cream", "Cook chicken in creamy tomato sauce"],
        ["Fish and Chips", "British", 35, 2, "Fish, potatoes, batter", "Batter and fry fish, make chips"],
        ["Chocolate Cake", "Dessert", 50, 8, "Flour, cocoa, eggs, sugar", "Mix, bake, frost with chocolate"],
    ]

    for recipe in recipes:
        ws.append(recipe)

    wb.save(filepath)
    print(f"Created: {filepath}")


def create_valid_recipes_csv() -> None:
    """Create sample_recipes.csv with 10 valid recipes."""
    filepath = TEST_DATA_DIR / "sample_recipes.csv"

    headers = ["Recipe Name", "Category", "Prep Time (min)", "Servings", "Ingredients", "Instructions"]

    recipes = [
        ["Spaghetti Carbonara", "Italian", "30", "4", "Pasta, eggs, bacon, parmesan", "Cook pasta, mix with egg mixture and bacon"],
        ["Chicken Tikka Masala", "Indian", "45", "6", "Chicken, tomatoes, cream, spices", "Marinate chicken, grill, simmer in sauce"],
        ["Caesar Salad", "American", "15", "2", "Romaine, croutons, parmesan, dressing", "Toss lettuce with dressing and toppings"],
        ["Beef Tacos", "Mexican", "25", "4", "Ground beef, tortillas, toppings", "Brown beef, assemble tacos with toppings"],
        ["Pad Thai", "Thai", "35", "3", "Rice noodles, shrimp, peanuts, sauce", "Stir-fry noodles with shrimp and sauce"],
        ["French Onion Soup", "French", "60", "4", "Onions, beef broth, bread, cheese", "Caramelize onions, add broth, top with cheese"],
        ["Greek Salad", "Greek", "10", "4", "Cucumber, tomato, feta, olives", "Chop vegetables, add cheese and dressing"],
        ["Butter Chicken", "Indian", "40", "5", "Chicken, butter, tomatoes, cream", "Cook chicken in creamy tomato sauce"],
        ["Fish and Chips", "British", "35", "2", "Fish, potatoes, batter", "Batter and fry fish, make chips"],
        ["Chocolate Cake", "Dessert", "50", "8", "Flour, cocoa, eggs, sugar", "Mix, bake, frost with chocolate"],
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(recipes)

    print(f"Created: {filepath}")


def create_invalid_recipes_xlsx() -> None:
    """Create sample_invalid.xlsx with only 5 recipes (insufficient)."""
    filepath = TEST_DATA_DIR / "sample_invalid.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Recipes"

    # Headers
    headers = ["Recipe Name", "Category", "Prep Time (min)", "Servings"]
    ws.append(headers)

    # Only 5 recipes (should fail validation when 10 requested)
    recipes = [
        ["Spaghetti Carbonara", "Italian", 30, 4],
        ["Chicken Tikka Masala", "Indian", 45, 6],
        ["Caesar Salad", "American", 15, 2],
        ["Beef Tacos", "Mexican", 25, 4],
        ["Pad Thai", "Thai", 35, 3],
    ]

    for recipe in recipes:
        ws.append(recipe)

    wb.save(filepath)
    print(f"Created: {filepath}")


def create_empty_xlsx() -> None:
    """Create sample_empty.xlsx with headers only."""
    filepath = TEST_DATA_DIR / "sample_empty.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Recipes"

    # Headers only, no data
    headers = ["Recipe Name", "Category", "Prep Time (min)", "Servings"]
    ws.append(headers)

    wb.save(filepath)
    print(f"Created: {filepath}")


def main() -> None:
    """Generate all test data files."""
    print("Generating test data files...")
    print("=" * 50)

    create_test_data_dir()
    create_valid_recipes_xlsx()
    create_valid_recipes_csv()
    create_invalid_recipes_xlsx()
    create_empty_xlsx()

    print("=" * 50)
    print("Test data generation complete!")


if __name__ == "__main__":
    main()
