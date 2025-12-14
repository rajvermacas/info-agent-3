"""Generate test data files for Mail Agent testing.

Creates sample Excel and CSV files with recipe data for testing the agent.
"""

import csv
from pathlib import Path

from openpyxl import Workbook


def create_valid_recipes_xlsx(output_path: Path) -> None:
    """Create valid Excel file with 10 food recipes."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Recipes"

    # Headers
    ws.append(["Recipe Name", "Cuisine", "Prep Time (min)", "Difficulty", "Main Ingredient"])

    # 10 valid recipes
    recipes = [
        ["Spaghetti Carbonara", "Italian", 20, "Easy", "Pasta"],
        ["Chicken Tikka Masala", "Indian", 45, "Medium", "Chicken"],
        ["Beef Tacos", "Mexican", 30, "Easy", "Beef"],
        ["Pad Thai", "Thai", 25, "Medium", "Rice Noodles"],
        ["Greek Salad", "Greek", 15, "Easy", "Vegetables"],
        ["Sushi Rolls", "Japanese", 40, "Hard", "Rice"],
        ["French Onion Soup", "French", 60, "Medium", "Onions"],
        ["Caesar Salad", "American", 15, "Easy", "Lettuce"],
        ["Chicken Stir Fry", "Chinese", 20, "Easy", "Chicken"],
        ["Margherita Pizza", "Italian", 30, "Medium", "Dough"],
    ]

    for recipe in recipes:
        ws.append(recipe)

    wb.save(output_path)
    print(f"Created: {output_path}")


def create_invalid_recipes_xlsx(output_path: Path) -> None:
    """Create invalid Excel file with only 5 recipes (insufficient for typical 10-recipe request)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Recipes"

    # Headers
    ws.append(["Recipe Name", "Cuisine", "Prep Time (min)", "Difficulty", "Main Ingredient"])

    # Only 5 recipes (invalid if request was for 10)
    recipes = [
        ["Spaghetti Carbonara", "Italian", 20, "Easy", "Pasta"],
        ["Chicken Tikka Masala", "Indian", 45, "Medium", "Chicken"],
        ["Beef Tacos", "Mexican", 30, "Easy", "Beef"],
        ["Pad Thai", "Thai", 25, "Medium", "Rice Noodles"],
        ["Greek Salad", "Greek", 15, "Easy", "Vegetables"],
    ]

    for recipe in recipes:
        ws.append(recipe)

    wb.save(output_path)
    print(f"Created: {output_path}")


def create_recipes_csv(output_path: Path) -> None:
    """Create CSV file with 10 food recipes."""
    recipes = [
        ["Recipe Name", "Cuisine", "Prep Time (min)", "Difficulty", "Main Ingredient"],
        ["Spaghetti Carbonara", "Italian", "20", "Easy", "Pasta"],
        ["Chicken Tikka Masala", "Indian", "45", "Medium", "Chicken"],
        ["Beef Tacos", "Mexican", "30", "Easy", "Beef"],
        ["Pad Thai", "Thai", "25", "Medium", "Rice Noodles"],
        ["Greek Salad", "Greek", "15", "Easy", "Vegetables"],
        ["Sushi Rolls", "Japanese", "40", "Hard", "Rice"],
        ["French Onion Soup", "French", "60", "Medium", "Onions"],
        ["Caesar Salad", "American", "15", "Easy", "Lettuce"],
        ["Chicken Stir Fry", "Chinese", "20", "Easy", "Chicken"],
        ["Margherita Pizza", "Italian", "30", "Medium", "Dough"],
    ]

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(recipes)

    print(f"Created: {output_path}")


def create_empty_xlsx(output_path: Path) -> None:
    """Create empty Excel file (no data rows, only headers)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Recipes"

    # Only headers, no data
    ws.append(["Recipe Name", "Cuisine", "Prep Time (min)", "Difficulty", "Main Ingredient"])

    wb.save(output_path)
    print(f"Created: {output_path}")


def create_malformed_xlsx(output_path: Path) -> None:
    """Create malformed Excel file (invalid structure)."""
    # Create a valid file first, then corrupt it
    wb = Workbook()
    ws = wb.active
    ws.title = "Malformed"

    # Add inconsistent data (missing columns, wrong types)
    ws.append(["Recipe Name", "Cuisine"])  # Incomplete headers
    ws.append(["Pasta"])  # Missing columns
    ws.append(["Chicken", "Indian", "Extra", "Too", "Many", "Columns"])  # Too many columns
    ws.append([None, None, None])  # Null values

    wb.save(output_path)
    print(f"Created: {output_path}")


def main():
    """Generate all test data files."""
    test_data_dir = Path(__file__).parent.parent / "test_data"
    test_data_dir.mkdir(exist_ok=True)

    create_valid_recipes_xlsx(test_data_dir / "sample_recipes_valid.xlsx")
    create_invalid_recipes_xlsx(test_data_dir / "sample_recipes_invalid.xlsx")
    create_recipes_csv(test_data_dir / "sample_recipes.csv")
    create_empty_xlsx(test_data_dir / "sample_empty.xlsx")
    create_malformed_xlsx(test_data_dir / "sample_malformed.xlsx")

    print("\nAll test data files created successfully!")


if __name__ == "__main__":
    main()
