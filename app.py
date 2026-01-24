import firebase_admin
import os, json
from firebase_admin import credentials, firestore
from flask import Flask, flash, redirect, render_template, request, session, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from helpers import apology, login_required
from datetime import datetime as dt
import google.genai as genai

firebase_creds = json.loads(os.environ["FIREBASE_CREDENTIALS"])

cred = credentials.Certificate(firebase_creds)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Initialize Flask App
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key')
app.config["SESSION_PERMANENT"] = False
def get_user_food_data():
    """Get all food data for current user from Firestore - TODAY ONLY."""
    try:
        user_id = session.get("user_id")
        if not user_id:
            return {}, []
        
        # Get user data
        user_ref = db.collection("users").document(user_id).get()
        if not user_ref.exists:
            return {}, []
        
        user_data = user_ref.to_dict()
        
        # Get all food entries for today
        today = dt.now().strftime("%Y-%m-%d")
        food_entries = []
        
        try:
            meals_query = db.collection("users").document(user_id).collection("meals").where(
                "date", "==", today
            ).stream()
            
            for meal_doc in meals_query:
                meal_data = meal_doc.to_dict()
                serving = float(meal_data.get("serving", 1))  # Convert to float
                carb = float(meal_data.get("carb", 0))
                protein = float(meal_data.get("protein", 0))
                kcal = float(meal_data.get("kcal", 0))
                
                food_entries.append({
                    "meal_id": meal_doc.id,
                    "food_name": meal_data.get("food_name", ""),
                    "serving": serving,
                    "carbs": round(carb * serving, 2),
                    "protein": round(protein * serving, 2),
                    "kcal": round(kcal * serving, 2)
                })
        except Exception as e:
            print(f"Error fetching meals: {e}")
        
        return user_data, food_entries
    except Exception as e:
        print(f"Error in get_user_food_data: {e}")
        return {}, []

def calculate_totals(food_entries):
    """Calculate total calories, carbs, and protein from food entries."""
    total_carbs = sum(entry["carbs"] for entry in food_entries)
    total_protein = sum(entry["protein"] for entry in food_entries)
    total_calories = sum(entry["kcal"] for entry in food_entries)
    
    return round(total_calories, 2), round(total_carbs, 2), round(total_protein, 2)

def parse_recipe_response(recipe_text):
    """Parse Gemini recipe response into structured data."""
    try:
        recipe_data = {
            "name": "",
            "ingredients": [],
            "steps": [],
            "calories": 0,
            "protein": 0,
            "carbs": 0,
            "raw_content": recipe_text
        }
        
        # Extract recipe name - handle both newline and inline formats
        name_start = recipe_text.find("**Recipe Name:**")
        if name_start != -1:
            name_start += len("**Recipe Name:**")
            # Try to find next ** marker (new section)
            name_end = recipe_text.find("**", name_start)
            if name_end == -1:
                # No more markers, look for newline
                name_end = recipe_text.find("\n", name_start)
            if name_end == -1:
                # No newline either, take rest
                name_end = len(recipe_text)
            recipe_data["name"] = recipe_text[name_start:name_end].strip()
        
        # Extract ingredients
        ingredients_start = recipe_text.find("**Ingredients:**")
        steps_start = recipe_text.find("**Steps:**")
        if ingredients_start != -1 and steps_start != -1:
            ingredients_text = recipe_text[ingredients_start:steps_start]
            # Remove the header and split by - or newline
            ingredients_text = ingredients_text.replace("**Ingredients:**", "")
            for item in ingredients_text.split("-"):
                ingredient = item.strip()
                if ingredient and ingredient.startswith("**") is False:
                    recipe_data["ingredients"].append(ingredient)
        
        # Extract steps
        nutrition_start = recipe_text.find("**Nutrition:**")
        if steps_start != -1:
            if nutrition_start != -1:
                steps_text = recipe_text[steps_start:nutrition_start]
            else:
                steps_text = recipe_text[steps_start:]
            
            # Remove the header
            steps_text = steps_text.replace("**Steps:**", "")
            
            # Split by numbers (1., 2., etc.)
            import re
            step_pattern = r'\d+\.\s+(.+?)(?=\d+\.|$)'
            steps = re.findall(step_pattern, steps_text, re.DOTALL)
            for step in steps:
                step_text = step.strip()
                if step_text:
                    recipe_data["steps"].append(step_text)
        
        # Extract nutrition info
        if nutrition_start != -1:
            nutrition_text = recipe_text[nutrition_start:]
            
            # Extract calories
            cal_match = nutrition_text.find("Calories:")
            if cal_match != -1:
                cal_start = cal_match + len("Calories:")
                cal_end = nutrition_text.find(",", cal_start)
                if cal_end == -1:
                    cal_end = nutrition_text.find("\n", cal_start)
                try:
                    recipe_data["calories"] = float(nutrition_text[cal_start:cal_end].strip())
                except ValueError:
                    pass
            
            # Extract protein
            protein_match = nutrition_text.find("Protein:")
            if protein_match != -1:
                protein_start = protein_match + len("Protein:")
                protein_end = nutrition_text.find("g", protein_start)
                if protein_end != -1:
                    try:
                        recipe_data["protein"] = float(nutrition_text[protein_start:protein_end].strip())
                    except ValueError:
                        pass
            
            # Extract carbs
            carbs_match = nutrition_text.find("Carbs:")
            if carbs_match != -1:
                carbs_start = carbs_match + len("Carbs:")
                carbs_end = nutrition_text.find("g", carbs_start)
                if carbs_end != -1:
                    try:
                        recipe_data["carbs"] = float(nutrition_text[carbs_start:carbs_end].strip())
                    except ValueError:
                        pass
        
        return recipe_data
    except Exception as e:
        print(f"Error parsing recipe: {e}")
        return None

def format_recipe_html(recipe_data):
    """Format parsed recipe data into HTML."""
    html = f"<h2 style='color: #2c3e50; margin-bottom: 1.5rem;'>{recipe_data.get('name', 'Recipe')}</h2>"
    
    if recipe_data.get('ingredients'):
        html += "<h4 class='section-title' style='border-bottom: 2px solid #4CAF50; padding-bottom: 0.5rem;'>Ingredients</h4>"
        for ingredient in recipe_data['ingredients']:
            html += f"<div class='ingredient-item'>🥗 {ingredient}</div>"
    
    if recipe_data.get('steps'):
        html += "<h4 class='section-title' style='margin-top: 1.5rem; border-bottom: 2px solid #4CAF50; padding-bottom: 0.5rem;'>Steps</h4>"
        for i, step in enumerate(recipe_data['steps'], 1):
            html += f"<div class='step-item'><strong>Step {i}:</strong> {step}</div>"
    
    return html

@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

@app.route("/", methods=["GET"])
@login_required
def index():
    """Display Calories and main dashboard"""
    try:
        user_data, food_entries = get_user_food_data()
        
        if not user_data:
            return apology("User not found")
        
        total_calories, total_carbs, total_protein = calculate_totals(food_entries)
        recommended_calories = user_data.get("rec_cal", 2500)
        
        return render_template(
            "calorie.html",
            title="Home",
            Calorie_value=total_calories,
            Protein_value=total_protein,
            Carb_value=total_carbs,
            username=user_data.get("username", ""),
            bmi_value=round(user_data.get("bmi", 0), 2),
            calories_consumed=total_calories,
            carb_consumed=total_carbs,
            protein_consumed=total_protein,
            recommended_calories=round(recommended_calories, 2),
            weight=round(user_data.get("weight", 0), 2),
            food_data=food_entries
        )
    except Exception as e:
        print(f"Error in index: {e}")
        return apology("Error loading dashboard")

@app.route('/modmeal', methods=['POST'])
@login_required
def modmeal():
    """Modify meal servings or delete meals."""
    try:
        user_id = session.get("user_id")
        items_data = request.form.getlist('items')
        
        if not items_data:
            flash("No items to modify")
            return redirect('/')
        
        try:
            modified_items = [json.loads(item) for item in items_data]
        except json.JSONDecodeError:
            flash("Invalid data format")
            return redirect('/')
        
        for item in modified_items:
            meal_id = item.get('meal_id')
            serving = item.get('serving')
            delitem = item.get('delitem')
            
            if delitem == 'true':
                # Delete meal
                db.collection("users").document(user_id).collection("meals").document(meal_id).delete()
            else:
                # Update serving
                try:
                    serving = float(serving)
                    db.collection("users").document(user_id).collection("meals").document(meal_id).update({
                        "serving": serving
                    })
                except (ValueError, TypeError):
                    flash("Invalid serving amount")
                    continue
        
        flash("Meals updated")
    except Exception as e:
        print(f"Error in modmeal: {e}")
        flash("Error updating meals")
    
    return redirect('/')


@app.route("/login", methods=["GET", "POST"])
def login():
    """User login"""
    session.clear()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        
        if not username or not password:
            return apology("Username and password required")
        
        try:
            user_ref = db.collection("users").document(username).get()
            if user_ref.exists:
                user_data = user_ref.to_dict()
                if check_password_hash(user_data.get("password_hash", ""), password):
                    session["user_id"] = username
                    return redirect("/")
                else:
                    return apology("Invalid credentials")
            else:
                return apology("Invalid credentials")
        except Exception as e:
            print(f"Login error: {e}")
            return apology("Login error")
    
    return render_template("login.html", title="Login")

@app.route("/register", methods=["GET", "POST"])
def register():
    """Register new user"""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        weight_str = request.form.get("weight", "")
        height_str = request.form.get("height", "")
        password = request.form.get("password", "")
        confirm_password = request.form.get("conf-password", "")
        
        # Validation
        if not username:
            return apology("Username required")
        if not weight_str or not height_str:
            return apology("Weight and height required")
        if not password or password != confirm_password:
            return apology("Passwords must match")
        
        try:
            weight = float(weight_str)
            height = float(height_str)
        except ValueError:
            return apology("Weight and height must be numbers")
        
        # Check if user exists
        try:
            user_ref = db.collection("users").document(username).get()
            if user_ref.exists:
                return apology("Username already exists")
        except Exception as e:
            print(f"Check user error: {e}")
            return apology("Registration error")
        
        # Calculate BMI and recommended calories
        bmi = weight / ((height / 100) ** 2)
        
        if 18.5 <= bmi < 25:
            reccal = 2500
        elif bmi < 18.5:
            reccal = 2850
        else:
            reccal = 2200
        
        # Create user in Firestore
        try:
            hashed_password = generate_password_hash(password)
            db.collection("users").document(username).set({
                "username": username,
                "password_hash": hashed_password,
                "weight": weight,
                "height": height,
                "bmi": bmi,
                "rec_cal": reccal,
                "created_at": dt.now().isoformat()
            })
            
            flash("Registration successful")
            return redirect("/login")
        except Exception as e:
            print(f"Registration error: {e}")
            return apology("Registration error")
    
    return render_template("register.html", title="Register")


@app.route("/api/getUserDetails", methods=["GET", "POST"])
@login_required
def api_getUserDetails():
    """API to get/update user details"""
    user_id = session.get("user_id")
    
    if request.method == "GET":
        try:
            user_ref = db.collection("users").document(user_id).get()
            if user_ref.exists:
                user_data = user_ref.to_dict()
                return jsonify({
                    "username": user_data.get("username"),
                    "weight": user_data.get("weight"),
                    "height": user_data.get("height"),
                    "bmi": user_data.get("bmi")
                })
            else:
                return jsonify({"error": "User not found"}), 404
        except Exception as e:
            print(f"Get user error: {e}")
            return jsonify({"error": "Error fetching user"}), 500
    
    elif request.method == "POST":
        try:
            data = request.get_json()
            new_height = float(data.get("height", 0))
            new_weight = float(data.get("weight", 0))
            
            if new_height <= 0 or new_weight <= 0:
                return jsonify({"error": "Invalid values"}), 400
            
            # Calculate new BMI
            new_bmi = new_weight / ((new_height / 100) ** 2)
            
            if 18.5 <= new_bmi < 25:
                new_reccal = 2500
            elif new_bmi < 18.5:
                new_reccal = 2850
            else:
                new_reccal = 2200
            
            # Update Firestore
            db.collection("users").document(user_id).update({
                "height": new_height,
                "weight": new_weight,
                "bmi": new_bmi,
                "rec_cal": new_reccal,
                "updated_at": dt.now().isoformat()
            })
            
            return jsonify({"status": "success"})
        except ValueError:
            return jsonify({"error": "Invalid input"}), 400
        except Exception as e:
            print(f"Update user error: {e}")
            return jsonify({"error": "Update error"}), 500

@app.route("/history", methods=["GET", "POST"])
@login_required
def history():
    """View meal history by date"""
    if request.method == "GET":
        return render_template("history.html", title="History")
    
    elif request.method == "POST":
        try:
            user_id = session.get("user_id")
            date_obj = request.get_json().get("date")
            
            if not date_obj:
                return jsonify({"error": "Date required"}), 400
            
            # Format date
            date_str = f"{date_obj['year']}-{date_obj['month']:02d}-{date_obj['day']:02d}"
            
            # Query meals for date
            meals = []
            try:
                meals_query = db.collection("users").document(user_id).collection("meals").where(
                    "date", "==", date_str
                ).stream()
                
                for meal_doc in meals_query:
                    meal_data = meal_doc.to_dict()
                    serving = float(meal_data.get("serving", 1))
                    carb = float(meal_data.get("carb", 0))
                    protein = float(meal_data.get("protein", 0))
                    kcal = float(meal_data.get("kcal", 0))
                    
                    meals.append({
                        "food_name": meal_data.get("food_name"),
                        "serving": serving,
                        "carb": round(carb * serving, 2),
                        "protein": round(protein * serving, 2),
                        "total_cal": round(kcal * serving, 2)
                    })
            except Exception as e:
                print(f"History query error: {e}")
            
            if not meals:
                return jsonify({"status": "Empty", "message": "No meals for this date"})
            
            return jsonify(meals)
        except Exception as e:
            print(f"History error: {e}")
            return jsonify({"error": "History error"}), 500


@app.route("/addmeal", methods=["GET", "POST"])
@login_required
def addmeal():
    """Add meal for user"""
    user_id = session.get("user_id")
    
    if request.method == "POST":
        try:
            food_name = request.form.get("meal", "").strip()
            serving_str = request.form.get("serving", "")
            
            if not food_name or not serving_str:
                flash("Food and serving required")
                return redirect('/')
            
            try:
                serving = float(serving_str)
                if serving <= 0:
                    flash("Serving must be > 0")
                    return redirect('/')
            except ValueError:
                flash("Invalid serving")
                return redirect('/')
            
            # Get food from database (check both food_data and recipes)
            try:
                food_docs = db.collection("food_data").where(
                    "food_name", "==", food_name
                ).limit(1).stream()
                
                food_data = None
                for doc in food_docs:
                    food_data = doc.to_dict()
                    break
                
                # If not found in food_data, check recipes collection
                if not food_data:
                    recipe_docs = db.collection("recipes").where(
                        "name", "==", food_name
                    ).limit(1).stream()
                    
                    for doc in recipe_docs:
                        recipe = doc.to_dict()
                        # Convert recipe format to food format
                        food_data = {
                            "unit_serving_carb_g": recipe.get("carbs", 0),
                            "unit_serving_protein_g": recipe.get("protein", 0),
                            "unit_serving_energy_kcal": recipe.get("calories", 0)
                        }
                        break
                
                if not food_data:
                    flash("Food not found")
                    return redirect('/')
            except Exception as e:
                print(f"Food lookup error: {e}")
                flash("Food lookup error")
                return redirect('/')
            
            # Add meal to Firestore
            try:
                today = dt.now().strftime("%Y-%m-%d")
                db.collection("users").document(user_id).collection("meals").add({
                    "food_name": food_name,
                    "serving": serving,
                    "carb": food_data.get("unit_serving_carb_g", 0),
                    "protein": food_data.get("unit_serving_protein_g", 0),
                    "kcal": food_data.get("unit_serving_energy_kcal", 0),
                    "date": today,
                    "added_at": dt.now().isoformat()
                })
                
                flash(f"Added {food_name}")
            except Exception as e:
                print(f"Add meal error: {e}")
                flash("Add error")
            
            return redirect('/')
        except Exception as e:
            print(f"Add meal error: {e}")
            flash("Add error")
            return redirect('/')
    
    else:  # GET request - search for food or get food data
        try:
            # Check if getting specific food data
            food_name = request.args.get("food", "").strip()
            if food_name:
                try:
                    # First check food_data collection
                    food_docs = db.collection("food_data").where(
                        "food_name", "==", food_name
                    ).limit(1).stream()
                    
                    for doc in food_docs:
                        food_data = doc.to_dict()
                        return jsonify({
                            "calories": float(food_data.get("unit_serving_energy_kcal", 0)),
                            "carbs": float(food_data.get("unit_serving_carb_g", 0)),
                            "protein": float(food_data.get("unit_serving_protein_g", 0))
                        })
                    
                    # If not found in food_data, check recipes collection
                    recipe_id = food_name.lower().replace(" ", "_")
                    recipe_doc = db.collection("recipes").document(recipe_id).get()
                    
                    if recipe_doc.exists:
                        recipe_data = recipe_doc.to_dict()
                        return jsonify({
                            "calories": float(recipe_data.get("calories", 0)),
                            "carbs": float(recipe_data.get("carbs", 0)),
                            "protein": float(recipe_data.get("protein", 0))
                        })
                    
                    return jsonify({"error": "Food not found"}), 404
                except Exception as e:
                    print(f"Food data error: {e}")
                    return jsonify({"error": "Error fetching food"}), 500
            
            # Otherwise search for foods
            food_query = request.args.get("q", "").strip()
            
            if not food_query or len(food_query) < 1:
                return jsonify([])
            
            # Search in Firestore with collection scan (optimized for speed)
            foods = []
            foods_set = set()  # Use set to track duplicates
            try:
                food_query_lower = food_query.lower()
                # Limit to 100 documents for faster response
                food_docs = db.collection("food_data").limit(100).stream()
                
                for doc in food_docs:
                    food_name_doc = doc.to_dict().get("food_name", "")
                    if food_query_lower in food_name_doc.lower() and food_name_doc not in foods_set:
                        foods.append(food_name_doc)
                        foods_set.add(food_name_doc)
                        if len(foods) >= 10:
                            break
                
                # Also search shared recipes collection
                if len(foods) < 10:
                    recipes_docs = db.collection("recipes").limit(100).stream()
                    for doc in recipes_docs:
                        recipe_name = doc.to_dict().get("name", "")
                        if food_query_lower in recipe_name.lower() and recipe_name not in foods_set:
                            foods.append(recipe_name)
                            foods_set.add(recipe_name)
                            if len(foods) >= 10:
                                break
            except Exception as e:
                print(f"Food search error: {e}")
            
            return jsonify(foods)
        except Exception as e:
            print(f"Search error: {e}")
            return jsonify([])

@app.route("/make_food", methods=["GET", "POST"])
@login_required
def make_food():
    """Get recipe suggestion from Gemini API"""
    if request.method == "GET":
        try:
            user_id = session.get("user_id")
            user_ref = db.collection("users").document(user_id).get()
            
            if not user_ref.exists:
                return redirect('/')
            
            user_data = user_ref.to_dict()
            recommended_calories = user_data.get("rec_cal", 2500)
            
            # Get today's consumed calories
            user_data_obj, food_entries = get_user_food_data()
            total_calories, _, _ = calculate_totals(food_entries)
            remaining_calories = recommended_calories - total_calories
            
            # Determine meal time
            current_hour = dt.now().hour
            if current_hour < 12:
                time_of_day = "breakfast"
            elif current_hour < 17:
                time_of_day = "lunch"
            else:
                time_of_day = "dinner"
            
            return render_template(
                "make_food.html",
                remaining_calories=max(0, remaining_calories),
                time_of_day=time_of_day,
                recommended_calories=recommended_calories,
                calories_consumed=total_calories
            )
        except Exception as e:
            print(f"Make food GET error: {e}")
            flash("Recipe page error")
            return redirect('/')
    
    elif request.method == "POST":
        try:
            remaining_calories = request.form.get('remaining_calories', '0')
            time_of_day = request.form.get('time_of_day', 'meal')
            ingredients = request.form.get('ingredients', '')
            
            # Validate input
            try:
                remaining_calories = float(remaining_calories)
            except ValueError:
                flash("Invalid calorie input")
                return redirect('/make_food')
            
            # Create prompt
            prompt = f"""I have {remaining_calories} calories remaining for {time_of_day}. 

Available ingredients: {ingredients}

Suggest ONE recipe within this calorie limit.

Format:
**Recipe Name:** [name]
**Ingredients:**
- [ingredient 1]
- [ingredient 2]
**Steps:**
1. [step 1]
2. [step 2]
**Nutrition:** Calories: [X], Protein: [Xg], Carbs: [Xg]. 
The recipe name should be a general and intuitive one which other people should be able to guess. It should be at most 3 words
"""
            
            # Call Gemini API
            api_key = os.getenv('GEMINI_API')
            if not api_key:
                flash("API not configured")
                return redirect('/make_food')
            
            try:
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt
                )
                
                recipe_text = response.text
            except Exception as api_error:
                print(f"Gemini API error: {api_error}")
                flash("Could not generate recipe")
                return redirect('/make_food')
            
            # Parse recipe response
            recipe_data = parse_recipe_response(recipe_text)
            if not recipe_data:
                flash("Could not parse recipe")
                return redirect('/make_food')
            
            # Format recipe for display
            formatted_recipe = format_recipe_html(recipe_data)
            
            return render_template(
                'recipe.html',
                recipe_content=formatted_recipe,
                recipe_data=recipe_data,
                remaining_calories=remaining_calories,
                time_of_day=time_of_day
            )
        except Exception as e:
            print(f"Make food POST error: {e}")
            flash("Recipe error")
            return redirect('/make_food')


@app.route("/save_recipe", methods=["POST"])
@login_required
def save_recipe():
    """Save recipe as a meal to Firestore and update user nutrition."""
    try:
        user_id = session.get("user_id")
        data = request.get_json()
        
        print(f"DEBUG: Received data: {data}")
        
        recipe_data = data.get("recipe_data") if data else None
        meal_time = data.get("meal_time", "meal") if data else "meal"
        
        print(f"DEBUG: Recipe data: {recipe_data}")
        print(f"DEBUG: Meal time: {meal_time}")
        
        if not recipe_data or not isinstance(recipe_data, dict):
            print(f"ERROR: Invalid recipe data: {recipe_data}")
            return jsonify({"error": "No recipe data or invalid format"}), 400
        
        if not recipe_data.get("name"):
            print(f"ERROR: Recipe missing name")
            return jsonify({"error": "Recipe must have a name"}), 400
        
        try:
            # Ensure numeric values are floats
            calories = float(recipe_data.get("calories", 0))
            protein = float(recipe_data.get("protein", 0))
            carbs = float(recipe_data.get("carbs", 0))
            
            recipe_name = recipe_data.get("name", "Recipe")
            recipe_id = recipe_name.lower().replace(" ", "_")
            today = dt.now().strftime("%Y-%m-%d")
            
            print(f"DEBUG: Creating meal doc with: name={recipe_name}, cal={calories}, protein={protein}, carbs={carbs}")
            
            # Add to user's meals collection
            meal_doc = {
                "food_name": recipe_name,
                "serving": 1.0,
                "carb": carbs,
                "protein": protein,
                "kcal": calories,
                "date": today,
                "meal_type": meal_time,
                "is_recipe": True,
                "recipe_details": {
                    "ingredients": recipe_data.get("ingredients", []),
                    "steps": recipe_data.get("steps", [])
                },
                "created_at": dt.now().isoformat()
            }
            
            print(f"DEBUG: Adding meal to user's collection: {meal_doc}")
            meal_ref = db.collection("users").document(user_id).collection("meals").add(meal_doc)
            print(f"DEBUG: Meal added with ID: {meal_ref}")
            
            # Also add to shared recipes collection for everyone to see
            recipe_doc = {
                "name": recipe_name,
                "calories": calories,
                "protein": protein,
                "carbs": carbs,
                "ingredients": recipe_data.get("ingredients", []),
                "steps": recipe_data.get("steps", []),
                "created_by": user_id,
                "created_at": dt.now().isoformat(),
                "times_used": firestore.Increment(1)
            }
            
            print(f"DEBUG: Adding recipe to shared collection: {recipe_doc}")
            db.collection("recipes").document(recipe_id).set(recipe_doc, merge=True)
            print(f"DEBUG: Recipe added to shared collection")
            
            return jsonify({"status": "success", "message": "Recipe saved!"})
        except ValueError as e:
            print(f"ERROR: Value conversion error: {e}")
            return jsonify({"error": f"Invalid numeric values: {str(e)}"}), 400
    except Exception as e:
        print(f"ERROR: Save recipe error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Server error: {str(e)}"}), 500
