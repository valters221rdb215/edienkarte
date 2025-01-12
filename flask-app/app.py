from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import random

import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import pandas as pd
import os
from pymongo import MongoClient

app = Flask(__name__)
app.secret_key = "your_secret_key"

MONGO_URI = "mongodb://localhost:27017/"
DATABASE_NAME = "prolab"
USERS_COLLECTION = "users"
RECIPES_COLLECTION = "recipes"

client = MongoClient(MONGO_URI)
db = client[DATABASE_NAME]
users_collection = db[USERS_COLLECTION]
recipes_collection = db[RECIPES_COLLECTION]



def load_users():
    """Loads users from MongoDB."""
    try:
        user_doc = users_collection.find_one()
        if user_doc:
            print("User database loaded successfully.")
            del user_doc['_id']
            return user_doc
        else:
            print("No users found in the database. Starting with default user.")
            return {
                'testuser': {
                    'password': generate_password_hash('password123'),
                    'preferences': {},
                }
            }
    except Exception as e:
        print("Error loading user database:", e)
        return {}

users_db = load_users()



def load_recipes():
    """Loads recipes from MongoDB (from a single document with an array of recipes)."""
    try:
        recipes_doc = recipes_collection.find_one()
        if recipes_doc:
            recipes = recipes_doc.get('recipes', [])
            print("Recipes database loaded successfully.")
            return recipes
        else:
            print("No recipes found in the database.")
            return []
    except Exception as e:
        print("Error loading recipes database:", str(e))
        return []

recipes_list = load_recipes()



def calculate_bmr(sex, weight, height, age):
    if sex.lower() == "male":
        return 10 * weight + 6.25 * height - 5 * age + 5
    elif sex.lower() == "female":
        return 10 * weight + 6.25 * height - 5 * age - 161



def calculate_macros(age, bmr, sex):
    fat_percentage = 0.25 if age >= 19 else 0.30
    fat_grams = (fat_percentage * bmr) / 9
    carbohydrate_grams = (0.55 * bmr) / 4
    protein_grams = 56 if sex.lower() == "male" else 46
    return fat_grams, carbohydrate_grams, protein_grams



def parse_nutrition(nutrition_list):
    nutrition = {item['name']: item['amount'] for item in nutrition_list}
    fat = float(nutrition.get("Total Fat", "0g").replace("g", ""))
    carbs = float(nutrition.get("Total Carbohydrate", "0g").replace("g", ""))
    protein = float(nutrition.get("Protein", "0g").replace("g", ""))
    return fat, carbs, protein



def filter_recipes(recipes_list, unwanted_ingredients, wanted_ingredients):
    unwanted_ingredients = [ingredient.lower().strip() for ingredient in unwanted_ingredients if ingredient.strip()]
    wanted_ingredients = [ingredient.lower().strip() for ingredient in wanted_ingredients if ingredient.strip()]

    filtered_recipes = [
        recipe for recipe in recipes_list
        if not any(unwanted in ingredient['name'].lower() for unwanted in unwanted_ingredients for ingredient in recipe['ingredients'])
    ]

    if wanted_ingredients:
        filtered_recipes_with_wanted = [
            recipe for recipe in filtered_recipes
            if any(wanted in ingredient['name'].lower() for wanted in wanted_ingredients for ingredient in recipe['ingredients'])
        ]
        if filtered_recipes_with_wanted:
            return filtered_recipes_with_wanted

    return filtered_recipes



def generate_combinations(
    recipes_list, target_calories, target_protein, target_carbs, target_fat,
    unwanted_ingredients, wanted_ingredients, pinned_recipes, num_combinations=50000
):
    filtered_recipes = filter_recipes(recipes_list, unwanted_ingredients, wanted_ingredients)
    if not filtered_recipes:
        return []

    min_calories = target_calories * 1
    max_calories = target_calories * 1.2
    valid_combinations = []

    for _ in range(num_combinations):
        day_combination = {
            "recipes": [],
            "total_calories": 0,
            "total_protein": 0,
            "total_carbohydrate": 0,
            "total_fat": 0,
            "total_price": 0
        }

        sampled_recipes = random.sample(filtered_recipes, 3)
        for recipe in sampled_recipes:
            fat, carbs, protein = parse_nutrition(recipe['nutrition'])
            day_combination["recipes"].append({
                "name": recipe["id"],
                "url": recipe["url"],
                "servings": recipe["servings"],
                "portion": f"{recipe['servings']} serving(s)"
            })
            day_combination["total_calories"] += recipe["calories"]
            day_combination["total_fat"] += fat
            day_combination["total_carbohydrate"] += carbs
            day_combination["total_protein"] += protein
            day_combination["total_price"] += float(recipe["price"])

        if (
            min_calories <= day_combination["total_calories"] <= max_calories and
            (target_fat * 0.8) <= day_combination["total_fat"] <= (target_fat * 1.5) and
            (target_carbs * 0.8) <= day_combination["total_carbohydrate"] <= (target_carbs * 1.5) and
            (target_protein * 0.8) <= day_combination["total_protein"] <= (target_protein * 1.5)
        ):
            valid_combinations.append(day_combination)

    valid_combinations = sorted(valid_combinations, key=lambda x: x["total_price"])
    return valid_combinations[:5]



@app.route("/")
def index():
    return redirect(url_for('home'))



@app.route("/home")
def home():
    return render_template("home.html")



@app.route('/calculate', methods=['POST'])
def calculate():
    try:
        data = request.json
        age = int(data['age'])
        weight = float(data['weight'])
        height = float(data['height'])
        sex = data['sex']
        choice = data['choice']
        unwanted_ingredients = data.get('unwanted_ingredients', [])
        wanted_ingredients = data.get('wanted_ingredients', [])
        pinned_recipes = data.get('pinned_recipes', {})

        if choice == "suggested":
            bmr = calculate_bmr(sex, weight, height, age)
            fat_grams, carbohydrate_grams, protein_grams = calculate_macros(age, bmr, sex)
        elif choice == "custom":
            bmr = float(data.get('calories', 0))
            fat_grams = float(data.get('fat', 0))
            carbohydrate_grams = float(data.get('carbohydrates', 0))
            protein_grams = float(data.get('protein', 0))
        else:
            return jsonify({"error": "Please select a valid meal plan option."}), 400

        valid_combinations = generate_combinations(
            recipes_list, bmr, protein_grams, carbohydrate_grams, fat_grams,
            unwanted_ingredients, wanted_ingredients, pinned_recipes
        )

        if not valid_combinations:
            return jsonify({"error": "No valid meal combinations found with the given filters."}), 400

        days_data = []
        for i, combo in enumerate(valid_combinations):
            day_details = {
                "day": f"Day {i + 1}",
                "recipes": combo["recipes"],
                "total_calories": combo["total_calories"],
                "total_fat": combo["total_fat"],
                "total_carbohydrate": combo["total_carbohydrate"],
                "total_protein": combo["total_protein"],
                "total_price": combo["total_price"]
            }
            days_data.append(day_details)

        table_data = [{"Day": day["day"], 
                       "Price ($)": day["total_price"], 
                       "Calories": day["total_calories"], 
                       "Fat (g)": day["total_fat"], 
                       "Carbohydrates (g)": day["total_carbohydrate"], 
                       "Protein (g)": day["total_protein"]} for day in days_data]
        df = pd.DataFrame(table_data)
        table_html = df.to_html(index=False, classes='table table-striped table-bordered')

        prices = [day["total_price"] for day in days_data]
        plt.figure(figsize=(10, 5))
        plt.bar(range(1, len(prices) + 1), prices, tick_label=[f"Day {i}" for i in range(1, len(prices) + 1)])
        plt.xlabel('Days')
        plt.ylabel('Price ($)')
        plt.title('Daily Meal Prices')
        if not os.path.exists('static'):
            os.makedirs('static')
        chart_path = 'static/prices_chart.png'
        plt.savefig(chart_path)
        plt.close()

        response = {
            'bmr': round(bmr, 2),
            'fat': round(fat_grams, 2),
            'carbohydrates': round(carbohydrate_grams, 2),
            'protein': round(protein_grams, 2),
            'days_data': days_data,
            'prices_chart': chart_path,
            'meal_table': table_html
        }
        return jsonify(response)

    except Exception as e:
        print("Error in /calculate route:", str(e))
        return jsonify({"error": str(e)}), 500


 
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user_doc = users_collection.find_one()
        user = user_doc.get(username) if user_doc else None
        if user and check_password_hash(user['password'], password):
            session['user'] = username
            flash('Login successful!', 'success')
            return render_template('index.html')
        else:
            flash('Invalid username or password', 'danger')

    return render_template('login.html')



@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user_doc = users_collection.find_one()
        if user_doc and username in user_doc:
            flash('Username already exists', 'danger')
        else:
            users_collection.update_one(
                {},
                {'$set': {username: {'password': generate_password_hash(password), 'preferences': {}}}},
                upsert=True
            )
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))

    return render_template('register.html')



@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))



@app.errorhandler(KeyError)
def handle_key_error(e):
    return redirect(url_for('home'))



@app.route('/save_preferences', methods=['POST'])
def save_preferences():
    try:
        user = session['user']
        preferences = request.json

        users_collection.update_one(
            {},
            {'$set': {f'{user}.preferences': preferences}}
        )

        return jsonify({'message': 'Preferences saved successfully!'})
    except Exception as e:
        print("Error saving preferences:", e)
        return jsonify({'error': 'Failed to save preferences'}), 500



@app.route('/get_preferences', methods=['GET'])
def get_preferences():
    user = session['user']

    user_doc = users_collection.find_one()
    preferences = user_doc.get(user, {}).get('preferences', {}) if user_doc else {}

    return jsonify(preferences)



if __name__ == '__main__':
    app.run()