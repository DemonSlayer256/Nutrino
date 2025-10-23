from cs50 import SQL
import json
import os
from flask import Flask, flash, redirect, render_template, request, session, jsonify
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from helpers import apology, login_required

# Configure application
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY')
# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"

Session(app)

# Configure CS50 LibrProjectv2/templatesary to use SQLite database
db = SQL("sqlite:///neutrino.db")

reccal = 0
username = ""
carb = 0
protein = 0
calorie = 0
bmi = 0
weight = 0

def get_calories():
    """Get the calories, carbs, and protein for the current user."""
    global carb, calorie, protein, bmi, reccal, weight, username
    carb = 0
    calorie = 0
    protein = 0
    user = db.execute("SELECT username, weight, bmi, rec_cal FROM users WHERE id = ?", session["user_id"])
    bmi = user[0]["bmi"]
    reccal = user[0]["rec_cal"]
    weight = user[0]["weight"]
    username = user[0]["username"]
    try:
        food_data = db.execute(
            "SELECT food_name, unit_serving_carb_g as carb, unit_serving_protein_g as protein, unit_serving_energy_kcal as kcal, serving as s FROM ?, food_data WHERE food_data.food_code = ?.food_code AND date = CURRENT_DATE",
            user[0]["username"],
            user[0]["username"],
        )

        for i in food_data:
            carb += float(i["carb"]) * int(i["s"])
            calorie += float(i["kcal"]) * int(i["s"])
            protein += float(i["protein"]) * int(i["s"])
    except Exception as e:
        print(e)


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
    user = db.execute("SELECT username FROM users WHERE id = ?", session["user_id"])
    get_calories()
    try:
        food_data  = db.execute(
            """SELECT fid, food_name, serving, ROUND((unit_serving_carb_g * serving), 2) as carbs, ROUND((unit_serving_protein_g * serving), 2) as protein, ROUND((unit_serving_energy_kcal * serving), 2)
            as kcal FROM ?, food_data WHERE food_data.food_code = ?.food_code AND date = CURRENT_DATE""",
            user[0]["username"],
            user[0]["username"],
        )
        print(food_data)
    except Exception as e:
        print(f"Error occurred: {e}")
        food_data = {"status": "error", "message": "No data found for the current date"}
    if len(food_data) == 0:
        food_data = {"status": "error", "message": "No data found for the current date"}
    return render_template(
        "calorie.html",
        title="Home",
        Calorie_value=round(calorie, 2),
        Protein_value=round(protein, 2),
        Carb_value=round(carb, 2),
        username=user[0]["username"],
        bmi_value=round(bmi, 2),
        calories_consumed=round(calorie, 2),
        carb_consumed=round(carb, 2),
        protein_consumed=round(protein, 2),
        recommended_calories=round(reccal, 2),
        weight=round(weight, 2),
        food_data = food_data
    )

@app.route('/modmeal', methods=['POST'])
@login_required
def modmeal():
    global calorie, carb, protein, username
    calorie = 0
    carb = 0
    protein = 0
    print("Username =", username)
    items_data = request.form.getlist('items')
    try:
        modified_items = [json.loads(item) for item in items_data]
    except Exception as e:
        return jsonify({"status": "error", "message": "Invalid data format"}), 400
    try:
        for item in modified_items:
            print(item)
            if item['delitem'] == 'true':
                # Delete the item from the database
                db.execute(
                    "DELETE FROM ? WHERE fid = ?",
                    username,
                    item['fid']
                )
            else:
                # Update the item in the database
                db.execute(
                    "UPDATE ? SET serving = ? WHERE fid = ? AND date = CURRENT_DATE",
                    username,
                    item['serving'],
                    item['fid']
                )
        flash("Meal modified successfully")
    except Exception as e:
        flash("An error occurred while modifying the meal. error: " + str(e))
    return redirect('/')

@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()
    global username
    """Log user in"""
    username = ""
    if request.method == "POST":
        user = request.form.get("username")
        pasw = request.form.get("password")

        if not user:
            return apology("Must provide username")
        if not pasw:
            return apology("Must provide password")

        rows = db.execute(
            "SELECT id,username, hash from users WHERE username = ?", user
        )

        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], pasw):
            return apology("Invalid username and/or password")
        session["user_id"] = rows[0]["id"]
        username = rows[0]["username"]
        return redirect("/")
    else:
        return render_template("login.html", title="Login")

@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        user = request.form.get("username")
        weight = request.form.get("weight")
        height = request.form.get("height")
        bmi = None
        reccal = None
        if user is None or weight is None or height is None:
            return apology("Please fill all the required fields")
        try:
            bmi = float(weight) / (float(height)/100 * (float(height)/100))
            if bmi > 18.5 and bmi < 25:
                ideal = 'N'
                reccal = 2500
            elif bmi < 18.5:
                ideal = 'U'
                reccal = 2850
            elif bmi > 25:
                ideal = 'O'
                reccal = 2200
        except Exception as e:
            return apology("The Height and Weight fields should contain Numbers only")

        passw = request.form.get("password")
        conf = request.form.get("conf-password")

        if not passw or not conf or passw != conf:
            return apology("Please enter the password and confirm it properly")

        passw = generate_password_hash(passw)
        try:
            db.execute(
                "INSERT INTO users (username, hash, weight, height, bmi, ideal, rec_cal) VALUES (?, ?, ?, ?, ?, ?, ?)",
                user,
                passw,
                float(weight),
                float(height),
                bmi,
                ideal,
                reccal
            )
            db.execute(
                "CREATE TABLE ? (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, food_code CHAR(7), serving INT, total_cal NUMERIC, date DATE DEFAULT CURRENT_DATE)",
                user,
            )
        except Exception as e:
            return apology(f"Username already exists :{e}")
        flash("Registered successfully")
        return redirect("/")
    else:
        return render_template("register.html", title="Register")


@app.route("/apigetUserDetails", methods=["GET", "POST"])
@login_required
def api_getUserDetails():
    if request.method == "GET":
        data = db.execute(
            "SELECT username, weight, height, bmi FROM users WHERE id = ?",
            session["user_id"],
        )
        print(data)
        return data
    else:
        ideal = 'N'
        nheight = request.json.get("height")
        nweight = request.json.get("weight")
        global bmi, reccal
        if not nheight or not nweight:
            return apology("Must provide height and weight")
        bmi = None
        try:
            nheight = float(nheight)
            nweight = float(nweight)
            bmi = nweight / (nheight * nheight)
            if bmi > 18.5 and bmi < 25:
                ideal = 'N'
                reccal = 2500
            elif bmi < 18.5:
                ideal = 'U'
                reccal = 2850
            else:
                ideal = 'O'
                reccal = 2200
        except ValueError:
            return apology("Height and weight must be numbers")
        try:
            db.execute(
                "UPDATE users SET height = ?, weight = ?, bmi = ?, rec_cal = ?, ideal = ? WHERE id = ?",
                nheight,
                nweight,
                bmi,
                reccal,
                ideal,
                session["user_id"],
            )
        except Exception as e:
            return jsonify({"status": "error", "message": f"An error occurred: {e}"})
        global weight
        weight = nweight
        print(f"Updated weight: {weight}")
        return jsonify(
            {"status": "success", "message": "User details updated successfully"}
        )


@app.route("/history", methods=["GET", "POST"])
@login_required
def history():
    if request.method == "GET":
        return render_template("history.html", title="History")
    else:
        terms = []
        date = request.json.get("date")
        print(f"Received date: {date['year']}, {username}")
        if not date:
            return apology("Must provide a date")
        try:
            date = f"{date['year']}-{date['month']:02d}-{date['day']:02d}"
        except KeyError:
            return apology("Invalid date format")
        user = db.execute(
            "SELECT username FROM users WHERE id = ?", session["user_id"]
        )
        user = user[0]["username"]
        try:
            terms = db.execute(
                """SELECT food_name, serving, (unit_serving_carb_g * serving) as carb, (unit_serving_protein_g * serving) as protein,
                  (unit_serving_energy_kcal * serving) as total_cal FROM food_data,? WHERE ?.food_code = food_data.food_code AND DATE = ?""",
                user,
                user,
                date,
            )

        except Exception as e:
            print(f"Error occurred: {e}")
        print(f'length of terms = {len(terms)}')
        if len(terms) == 0:
            return jsonify({"status": "Empty", "message": "No data found for the given date"})
        print(terms)
        return jsonify(terms)


@app.route("/addmeal", methods=["GET", "POST"])
@login_required
def addmeal():
    if request.method == "POST":
        global username, calperday, food_data, calorie, carb, protein
        username = db.execute("SELECT username FROM users WHERE id = ?", session["user_id"])[0]["username"]
        calperday = 0
        food_data = 0
        calorie = 0
        carb = 0
        protein = 0
        foods = request.form.get("meal")
        serve = request.form.get("serving")
        food = db.execute(
            "SELECT food_name, unit_serving_energy_kcal, food_code, energy_kcal FROM food_data WHERE food_name = ? ",
            foods,
        )
        try:
            serve = float(serve)
        except:
            return apology("INT")
        db.execute("BEGIN TRANSACTION")
        try:
            print(f"username = {username}, food_code = {food[0]['food_code']}, serving = {serve}, total_cal = {float(food[0]['unit_serving_energy_kcal']) * serve}")
            db.execute(
                "INSERT INTO ? (food_code, serving, total_cal) VALUES (?, ?, ?)",
                username,
                food[0]["food_code"],
                serve,
                float(food[0]["unit_serving_energy_kcal"]) * serve,
            )
            calperday += float(food[0]["unit_serving_energy_kcal"]) * serve
        except Exception as a:
            db.execute("ROLLBACK")
            print(f"Error {a}")
            return apology("This food is not registered in the database")
        db.execute("COMMIT")
        flash(f"ADDED MEAL : {foods}")
        return redirect('/')
    else:
        food = request.args.get("q")
        data = db.execute(
            "SELECT food_name, unit_serving_energy_kcal, energy_kcal FROM food_data WHERE food_name LIKE ? LIMIT 7",
            "%" + food + "%",
        )
        try:
            data = jsonify(data)
            return data
        except Exception as e:
            print(f"Error occurred: {e}")


if __name__ == "__main__":
    app.run(debug=True)
