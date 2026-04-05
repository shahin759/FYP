from flask import Flask, render_template,url_for, redirect,request, session, flash,jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pdfminer.high_level import extract_text,extract_text_to_fp
from pdfminer.layout import LAParams
from flask_caching import Cache
from flask_mail import Mail, Message
import requests
import pandas as pd
import csv
import re
import io
import secrets
import ollama
import json

app = Flask(__name__)

app.secret_key = "12345678"

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///seeker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'support.seeker@gmail.com'
app.config['MAIL_PASSWORD'] = 'rdgt kwkr poup zdxg'
app.config['MAIL_DEFAULT_SENDER'] = 'support.seeker@gmail.com'

mail = Mail(app)
reset_tokens = {}
db = SQLAlchemy(app)

API_KEY = "7eabd148-3685-4360-be0c-555c97ec868c"
BASE_URL = "https://www.reed.co.uk/api/1.0"

app.config["CACHE_TYPE"] = "SimpleCache"
app.config["CACHE_DEFAULT_TIMEOUT"]=200

cache=Cache(app)


class User(db.Model): #user table   
    __tablename__="user"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(100))
    experience_level=db.Column(db.String(100))
    career_goal= db.Column(db.String(100))
    skills = db.relationship("UserSkill",back_populates="user",cascade="all, delete-orphan")

class Skill(db.Model):   #skill table
    __tablename__="skill"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    users = db.relationship("UserSkill",back_populates="skill",cascade="all, delete-orphan")

class UserSkill(db.Model):  #user skill table
    __tablename__="user_skill"
    id = db.Column(db.Integer, primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey("user.id"), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey("skill.id"), nullable=False)
    user = db.relationship("User", back_populates="skills")
    skill = db.relationship("Skill", back_populates="users")

    __table_args__ = (
        db.UniqueConstraint("user_id", "skill_id", name="unique_user_skill"),
    )

class SavedJobs(db.Model): #saved jobs table
    __tablename__ = "saved_jobs"
    id = db.Column(db.Integer, primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey("user.id"), nullable=False)
    job_id = db.Column(db.Integer, nullable=False)
    job_title = db.Column(db.String(200))
    employer_name = db.Column(db.String(200))
    min_salary=db.Column(db.String(200))
    max_salary=db.Column(db.String(200))
    job_description=db.Column(db.Text)
    job_url=db.Column(db.String(200))
    user = db.relationship("User", backref="saved_jobs")
    

    __table_args__ = (
        db.UniqueConstraint("user_id", "job_id", name="unique_user_saved_jobs"),
    )

def __repr__(self):
    return f'<User {self.email}>'

with app.app_context():
    db.create_all()
 

@app.route("/")  # home page, showcasing jobs
def home_page():
    search_keywords = request.args.get('keywords', '')
    location = request.args.get('location', '')
    page = int(request.args.get('page', 1))
    show_all = request.args.get('all') == '1'
    per_page = 22


    params = {}
    if search_keywords:
        params['keywords'] = search_keywords
    if location:
        params['locationName'] = location
     
    user= None
    user_skills = []
    user_profile_text = ""
    user_experience = ""
    user_goal = ""
    user_skill_count = 0

    if "user" in session:    #if user logged in , build their profile
        user = User.query.filter_by(email=session["user"]).first()
        if user:
            user_skills = [us.skill.name for us in user.skills]
            user_experience = (user.experience_level or "").lower()
            user_goal = (user.career_goal or "").lower()
            user_profile_text = build_user_profile_text(user)
            user_skill_count = len(user_skills)
            

    if "user" in session and user_goal and not search_keywords and not show_all:
        params['keywords'] = user_goal  # uses the users career goal as search word to display relevant jobs
 
    try:
        filtered = get_scored_jobs( #fetchs job from API and scores each job
             tuple(sorted(params.items())),user,tuple(user_skills),
             user_profile_text,user_experience,
             show_all,user_goal,search_keywords
        )

    except Exception as e:
        return f"Error fetching jobs: {e}", 500

  

    end = page * per_page
    jobs = filtered[:end]
    has_more = len(filtered) > end
    saved_job_ids = []
    if user:
        saved_job_ids = [s.job_id for s in SavedJobs.query.filter_by(user_id=user.id).all()]

    return render_template( 
        "home_page.html",
        jobs=jobs,search_keywords=search_keywords,
        location=location,show_all=show_all,
        total_results=len(filtered),page=page,
        has_more=has_more,user=user,saved_job_ids=saved_job_ids)

@app.route("/job/<int:job_id>") #job details page
def job_details(job_id):
    try:
        job = fetch_job(job_id)

        skills_list = load_skills("csv/skills.csv")  #loads job description and extract skills 
        job_desc = job.get("jobDescription") or ""
        job_desc_norm = " ".join(str(job_desc).lower().split())
        job_skills = extract_skills_from_description(job_desc_norm, skills_list)

        user_skills = []
        match_result = None
        match_reasoning = None
        recommended_courses = []
        missing_skills_tuple= None
        user=None
        is_saved = False

        
        if "user" in session:  #if user logged in compares the extracted skills to the users skill
            user = User.query.filter_by(email=session["user"]).first()
            if user:
                user_skills = [us.skill.name for us in user.skills]
                is_saved = SavedJobs.query.filter_by(user_id=user.id, job_id=job_id).first() is not None
            

                user_set = set()
                for s in user_skills:
                    user_set.add(s.lower().strip())

                job_set = set()
                for s in job_skills:
                    job_set.add(s.lower().strip())
                    
                

                matching = sorted(user_set & job_set)
                missing = sorted(job_set - user_set)

                combined_skills, profile_text = user_content_profile(user, skills_list)
                score = calculate_match(combined_skills, profile_text, job_skills, job_desc, job.get("jobTitle", ""))

                match_result = {
                    'score': score,
                    'matching_skills': matching,
                    'missing_skills': missing,
                    'total_matching': len(matching),
                    'job_total_skills': len(job_set)
                }
    

                if missing:
                    missing_skills_tuple = tuple(missing)

   
        job_title = job.get("jobTitle", "")

        if missing_skills_tuple:  #shows courses that address the missing skills
         recommended_courses = get_courses(missing_skills_tuple)
        else:
         recommended_courses = []

        similar_jobs = get_similar_jobs(job_id, job_title) # gets similar jobs

        job_experience = extract_experience_level(job.get("jobTitle", ""))
        experience_warning = None
        if user and user.experience_level and job_experience != "Not specified":
            if user.experience_level.lower() not in job_experience.lower():
                experience_warning = f"This role appears to be {job_experience} level. Your profile is set to {user.experience_level}." #warns users if they have different experience level to job

        return render_template(
            "job_details.html", job=job,job_skills=job_skills,
            user_skills=user_skills,match_result=match_result, 
            recommended_courses=recommended_courses,similar_jobs=similar_jobs,
            job_experience=job_experience,experience_warning=experience_warning, 
            match_reasoning=match_reasoning,user=user,is_saved=is_saved)

    except requests.RequestException as e:
        print(f"Error details: {e}")
        return f"Error fetching job details: {e}", 500


@app.route("/job/<int:job_id>/match_reasoning")   # allows for job details page to show whilst ollama generates
def job_match_reasoning(job_id):
    if "user" not in session:
        return jsonify({"reasoning": None, "error": "Not logged in"}), 401

    user = User.query.filter_by(email=session["user"]).first()
    if not user:
        return jsonify({"reasoning": None, "error": "User not found"}), 404

    try:
        job = fetch_job(job_id)

        skills_list = load_skills("csv/skills.csv") 
        job_desc = job.get("jobDescription") or ""
        job_desc_norm = " ".join(str(job_desc).lower().split())
        job_skills = extract_skills_from_description(job_desc_norm, skills_list)

        user_skills = [us.skill.name for us in user.skills]

        user_set = set()
        for s in user_skills:
            user_set.add(s.lower().strip())

        job_set = set()
        for s in job_skills:
            job_set.add(s.lower().strip())

        matching = sorted(user_set & job_set)
        missing = sorted(job_set - user_set)

        reasoning = explain_match_score(
            user_skills_tuple=tuple(user_skills),
            user_experience=user.experience_level or "",
            user_goal=user.career_goal or "",
            job_title=job.get("jobTitle", ""),
            matching_tuple=tuple(matching),
            missing_tuple=tuple(missing)
        )

        return jsonify({"reasoning": reasoning})

    except Exception as e:
        print(f"Reasoning error: {e}")

        return jsonify({"reasoning": None, "error": "Could not generate reasoning"}), 500

    
@app.route("/login", methods=["GET", "POST"])  #login page, 
def login_page():
 if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember')
        
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password, password):
            session['user'] = email
            if remember:
                session.permanent = True
            flash('Login successful!', 'success')
            return redirect(url_for('home_page'))
        else:
            flash('Invalid email or password', 'error')
            return redirect(url_for('login_page'))
    
 return render_template('login_page.html')

@app.route("/save_job/<int:job_id>", methods=["POST"])  # allows loged in users to save and unsave jobs
def save_job(job_id):
    if "user" not in session:
        return jsonify({"reasoning": None, "error": "Not logged in"}), 401

    user = User.query.filter_by(email=session["user"]).first()
    if not user:
        return jsonify({"reasoning": None, "error": "User not found"}), 404
    
    exists = SavedJobs.query.filter_by(user_id=user.id, job_id=job_id).first()
    
    if exists:
        db.session.delete(exists)
        db.session.commit()
        return jsonify ({"status": "unsaved"})
    
    try:
        job=fetch_job(job_id)
        saved=SavedJobs(user_id=user.id ,job_id=job_id,job_title=job.get("jobTitle"),
        job_description=job.get("jobDescription"),employer_name=job.get("employerName"),min_salary=job.get("minimumSalary")
    ,max_salary=job.get("maximumSalary"),job_url=job.get("url"))
        db.session.add(saved)
        db.session.commit()
        return jsonify({"status": "saved"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
        

@app.route("/saved_jobs", methods=["GET", "POST"]) #saved jobs page
def saved_jobs():
    if "user" not in session:
        flash("Login first", "error")
        return redirect(url_for("login_page"))

    user = User.query.filter_by(email=session["user"]).first()
    if not user:
        flash("User not found", "error")
        return redirect(url_for("login_page"))

    if request.method == "POST":
        job_id = request.form.get("job_id")
        saved = SavedJobs.query.filter_by(user_id=user.id, job_id=job_id).first()
        if saved:
            db.session.delete(saved)
            db.session.commit()
            flash("Job removed", "success")
        return redirect(url_for("saved_jobs"))

    saved = SavedJobs.query.filter_by(user_id=user.id).all()
    return render_template("saved_jobs.html", saved_jobs=saved)

@app.route("/signup", methods=["GET", "POST"])  #signup page allows users to signup
def signup_page():
  if request.method =='POST':
    firstname= request.form.get('firstname')
    lastname= request.form.get('lastname')
    email=request.form.get('email')
    password=request.form.get('password')
    confirm_password=request.form.get('confirm_password')
    
    if not email or '@' not in email:
        flash('Please enter a valid email address', 'error')
        return redirect(url_for('signup_page'))
    
    if len(password) < 8:
        flash('Password must be at least 8 characters', 'error')
        return redirect(url_for('signup_page'))

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash('Email already exists, signin to your account','error')
        return redirect(url_for('signup_page'))

    if password != confirm_password:
        flash('Passwords do not match!','error')
        return redirect(url_for('signup_page'))
        
    hashed_password = generate_password_hash(password)
    new_user = User(name= str(firstname) + " " + str(lastname) , email=email, password=hashed_password)
        
    db.session.add(new_user)
    db.session.commit()
        
  
    flash('Account created successfully! Please login.', 'success')
    return redirect(url_for('login_page'))
    
  return render_template('signup_page.html')
    
@app.route('/account-page', methods=['GET']) #account page, allowing users to view their details
def account_page():
    if 'user' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('login_page'))
    
    user = User.query.filter_by(email=session['user']).first()
  
    
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('login_page'))
    
    return render_template('account_page.html', user=user)

@app.route('/courses') #courses page showing the courses from csv file
def courses_page():
    search_course = request.args.get('courses', '').strip().lower()

    params = {}
    if search_course:
     params['courses'] = search_course
    try:
        df=pd.read_csv('csv/courses.csv')
        course_list=df.to_dict('records')
    except FileNotFoundError:
        flash("Courses file not found")
        return render_template('courses_page.html',courses=[])
        
    if search_course:
        course_list = [
            c for c in course_list
            if search_course in str(c.get('course_title', '')).lower()
            or search_course in str(c.get('provider', '')).lower()
            or search_course in str(c.get('skills', '')).lower()
        ]

    return render_template("courses_page.html",courses=course_list, search_course = request.args.get('courses', '').strip().lower(), total_results=len(course_list))


@app.route('/upload_cv', methods=["GET", "POST"]) # upload cv, allows user to complete their profile
def upload_cv():
    if 'user' not in session:
        flash('Login first', 'error')
        return redirect(url_for('login_page'))

    user = User.query.filter_by(email=session['user']).first()
   

    if not user:
        flash('User not found', 'error')
        return redirect(url_for('login_page'))

    if request.method == 'POST':
        action = request.form.get("action")

        if action == "add_skill":
            skill_input = request.form.get('skills', '').lower().strip()

            if not skill_input:
                flash("Enter a skill", "error")
                return redirect(url_for('upload_cv'))

            valid_skill = [s.lower() for s in load_skills("csv/skills.csv")]
            if skill_input not in valid_skill:
                flash(f"'{skill_input}' is not a valid skill, please enter a valid skill", "error")
                return redirect(url_for('upload_cv'))

            skill = Skill.query.filter_by(name=skill_input).first()
            if not skill:
                skill = Skill(name=skill_input)
                db.session.add(skill)
                db.session.flush()

            exists = UserSkill.query.filter_by(user_id=user.id,skill_id=skill.id).first()

            if exists:
                flash('You already added that skill', 'info')
            else:
                db.session.add(UserSkill(user_id=user.id, skill_id=skill.id))
                db.session.commit()
                flash('Skill added successfully', 'success')

      
        elif action == "delete_skill":
            skill_id = request.form.get("skill_id")
            link = UserSkill.query.filter_by(user_id=user.id,skill_id=skill_id).first()

            if link:
                db.session.delete(link)
                db.session.commit()
                flash("Skill removed", "success")

        elif action=="add_goals":
          goals_input=request.form.get("goals")
          user.career_goal=goals_input
          db.session.commit()
          flash("carrer goal added", "success")

        elif action == "delete_goal":
          user.career_goal = None
          db.session.commit()
          flash("Career goal removed", "success")
        
        elif action=="delete_all":
          UserSkill.query.filter_by(user_id=user.id).delete()
          db.session.commit()
          flash("All skills removed", "success")


        elif action=="save_experience":
            experience=request.form.get("experience")
            user.experience_level=experience
            db.session.commit()
            flash("saved","success")

    return render_template("upload_cv.html", user=user)




def extract_skills_from_description(text, skills): #finds the skills from job description
    found = set()
    for skill in sorted(skills, key=len, reverse=True):
        s = skill.strip()
        if not s:
            continue
        s_low = s.lower()
        pattern = r"\b" + re.escape(s_low) + r"\b"
        if re.search(pattern, text):
            found.add(s) 
    return sorted(found)


@app.route("/extract_skills_from_cv", methods=["POST"]) #allows user to upload PDF , all text is extracted and checked to find any recognised skill
def extract_skills_from_cv():
    if "user" not in session:
        flash("Login first", "error")
        return redirect(url_for("login_page"))

    user = User.query.filter_by(email=session["user"]).first()
    if not user:
        flash("User not found", "error")
        return redirect(url_for("login_page"))

    file = request.files.get("cv")
    if not file or file.filename == "":
        flash("Please choose a PDF", "error")
        return redirect(url_for("upload_cv"))

    if not allowed_file(file.filename):
        flash("Only PDF files are allowed", "error")
        return redirect(url_for("upload_cv"))

    try:
    
        pdf_bytes = file.read()
        output = io.StringIO()
        extract_text_to_fp(io.BytesIO(pdf_bytes), output, laparams=LAParams())
        cv_text = output.getvalue().lower()
        cv_text = re.sub(r"\s+", " ", cv_text).strip()

        if not cv_text:
            flash("Could not extract text from PDF", "error")
            return redirect(url_for("upload_cv"))

        skills_list = load_skills("csv/skills.csv")
        extracted = extract_skills_from_description(cv_text, skills_list)

        added = 0
        for name in extracted:
            skill = Skill.query.filter_by(name=name).first()
            if not skill:
                skill = Skill(name=name)
                db.session.add(skill)
                db.session.flush()

            exists = UserSkill.query.filter_by(
                user_id=user.id, skill_id=skill.id).first()
            if not exists:
                db.session.add(UserSkill(user_id=user.id, skill_id=skill.id))
                added += 1

        db.session.commit()
        flash(f"Found {len(extracted)} skills, added {added} new", "success")

    except Exception as e:
        print(f"CV error: {e}")
        flash("Error processing CV", "error")

    return redirect(url_for("upload_cv"))

    

    
@app.route('/edit_account', methods=["GET", "POST"]) # allows user to edit account details
def edit_account():
    if 'user' not in session:
        flash('Login first', 'error')
        return redirect(url_for('login_page'))

    user = User.query.filter_by(email=session['user']).first()
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('login_page'))

    if request.method == 'POST':
        action = request.form.get("action")

        if action == "update_email":
            new_email = request.form.get('email', '').strip()

            if not new_email:
                flash("Email cannot be empty", "error")
                return redirect(url_for("edit_account"))

            existing = User.query.filter_by(email=new_email).first()
            if existing and existing.id != user.id:
                flash("That email is already in use", "error")
                return redirect(url_for("edit_account"))

            user.email = new_email
            db.session.commit()
            session['user'] = new_email

            flash("Email updated", "success")
            return redirect(url_for("edit_account"))

        elif action == "update_password":
            new_password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            if new_password != confirm_password:
                flash("Passwords do not match", "error")
                return redirect(url_for("edit_account"))

            user.password = generate_password_hash(new_password)
            db.session.commit()

            flash("Password updated successfully", "success")
            return redirect(url_for("edit_account"))

        else:
            flash("Invalid action", "error")
            return redirect(url_for("edit_account"))

    return render_template("edit_account.html", user=user)

@app.route('/forgot_password', methods=["POST", "GET"]) #forgot password page, generates token to allow user to change password
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email').strip()
        user = User.query.filter_by(email=email).first()

        if user:
            token = secrets.token_urlsafe(24)
            reset_tokens[token] = email  
            link = url_for('reset_password', token=token, _external=True)
            try:
                msg = Message(
                    subject="Your Password reset link",
                    recipients=[email],
                    body=f"Click the link to reset your password\n{link}\n"
                )
                mail.send(msg)
                flash('Reset link sent to your email', 'success')
            except Exception as e:
                print(f"Mail error: {e}")
                flash('Error sending mail', 'error')
        else:
            flash('If account exists you will receive email link', 'info')
        return redirect(url_for('login_page'))
    return render_template("forgot_password.html")

@app.route('/reset_password/<token>',methods=["POST","GET"])#after user clicks email , they can reset password
def reset_password(token):
    email=reset_tokens.get(token)

    if not email:
        flash('Invalid link, please try again','error')
        return redirect(url_for('forgot_password'))
    
    if request.method=='POST':
        password1=request.form.get('password1')
        password2=request.form.get('password2')
    
        if password1 != password2: 
            flash('Passwords do not match', 'error')
            return render_template('reset_password.html', token=token,email=email)

        user = User.query.filter_by(email=email).first()
        if user:
            user.password = generate_password_hash(password1)
            db.session.commit()
            del reset_tokens[token]
            flash('Password updated successfully', 'success')
            return redirect(url_for('login_page'))

    return render_template('reset_password.html', token=token ,email=email)
    

def allowed_file(filename):   #checks if the uploaded file is a pdf, has to end with .pdf
    return filename.lower().endswith('.pdf')



def build_user_profile_text(user): #creates a text blob of the users skills, carrer goal and experience level
    skills = [us.skill.name for us in user.skills] if user else []
    parts = [" ".join(skills), user.career_goal or "", user.experience_level or ""]
    return " ".join([p for p in parts if p]).strip()


def extract_experience_level(job_title):  #extracts experience level from job title according to corresponding words
    title = (job_title or "").lower()

    if re.search(r"\b(junior|trainee|entry|graduate|grad|intern|apprentice)\b", title):
        return "Junior"

    elif re.search(r"\b(senior|manager|lead|principal|director|head)\b", title):
        return "Senior"

    elif re.search(r"\b(mid[- ]?level|intermediate)\b", title):
        return "Mid-level"
    else:
        return "Not specified"

@cache.memoize(timeout=3600) # Uses ollama to output a reason explaining the user's suitability for the role , is also cached.
def explain_match_score(user_skills_tuple, user_experience, user_goal, job_title, matching_tuple, missing_tuple):
    user_skills = list(user_skills_tuple)
    matching_skills = list(matching_tuple)
    missing_skills = list(missing_tuple)


    prompt = f"""write a very brief paragraph max 6 lines explaining why this is or isn't suitable for this user, be specific and tailored to the user and if it aligns to their experience level and career goal, no labels !!! , just explanation

    User:
    - Skills: {', '.join(user_skills)}
    - Career goal: {user_goal}
    - Experience level: {user_experience}

    Job: {job_title}
    Matching skills: {', '.join(matching_skills)}
    Missing skills: {', '.join(missing_skills)}  
    no labels and make it seem like your a careers advisor,make sure its just the reasoning nothing else"""

    try:
        response = ollama.chat(model='llama3.2:1b',messages=[{'role': 'user', 'content': prompt}],
)
        return response['message']['content'].strip()
    except Exception as e:
        print(f"Ollama error: {e}")
        return None

@app.route('/logout') # logout function
def logout():
    session.pop('user',None)
    flash('Logged out','success')
    return redirect (url_for('home_page'))

@app.route('/contact_us',methods=["GET", "POST"]) #contact us page, sends form to email
def contact_us():
    if request.method=="POST":
        name= request.form.get("name")
        email = request.form.get("email")
        subject = request.form.get("subject")
        message= request.form.get("message")
        try:
            msg = Message(subject=f"Contact Form: {subject}",recipients=[app.config['MAIL_USERNAME']])

            msg.body = f"""
            Name: {name} 
            Email: {email}
            Message:{message}"""

            msg.reply_to = email
            mail.send(msg)
            flash("Form sent", "success")

        except Exception as e:
            flash(f"Error", "error")

    return render_template("contact_us.html")


@app.route('/about_us') #about us page
def about_us():
       return render_template('about_us.html')


@cache.memoize(timeout=200) # calls Reed API to search for jobs using given parameters
def job_fetch(params_tuple):
    params=dict(params_tuple)
    response=requests.get(f"{BASE_URL}/search",params=params,auth=(API_KEY, ""),timeout=10)
    response.raise_for_status()
    return response.json()


@cache.memoize(timeout=600) #gets full detail of a job , for job details page
def fetch_job(job_id):
    response = requests.get(
        f"{BASE_URL}/jobs/{job_id}",auth=(API_KEY, ""),
        timeout=10
    )
    response.raise_for_status()
    return response.json()

@cache.memoize(timeout=3600) #returns a list of skills from skills.csv
def load_skills(path):
    skills = []
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if row:
                skill = row[0].strip()
                if skill.lower() != "skill":
                    skills.append(skill)

    return skills


def get_scored_jobs(params_tuple,user, user_skills_tuple, user_profile_text, user_experience, show_all, user_goal="",search_keywords=""):# gets user profile and scores jobs

    params = dict(params_tuple)
    
    skills_list = load_skills("csv/skills.csv")

    if user_goal and not show_all and not search_keywords:
        all_jobs = fetch_jobs(user_goal, user_experience, dict(params_tuple), user)
    else:
        data = job_fetch(params_tuple)
        all_jobs = data.get("results", [])[:50]

    if show_all:
        return all_jobs

    user_skills = list(user_skills_tuple)
    
    combined_skills = user_skills
    profile_text = user_profile_text
    
    if user:
        combined_skills, profile_text = user_content_profile(user, skills_list)

    for job in all_jobs:
        job_desc = job.get("jobDescription", "") or ""
        job_title = job.get("jobTitle", "") or ""
        job_desc_norm = " ".join(str(job_desc).lower().split())
        job_skills = extract_skills_from_description(job_desc_norm, skills_list)

        job["match_score"] = calculate_match(
            combined_skills, profile_text, job_skills, job_desc, job_title
        )
        job["experience_level"] = extract_experience_level(job_title)

    all_jobs.sort(key=lambda j: j.get("match_score", 0), reverse=True)

    if user_experience and not show_all:
        aligned_jobs = []
        for job in all_jobs:
            job_exp = job.get("experience_level", "Not specified")
            if job_exp == "Not specified" or user_experience.lower() in job_exp.lower():
                aligned_jobs.append(job)

        aligned_jobs.sort(key=lambda j: (
            0 if user_experience.lower() in j.get("experience_level", "").lower() else 1,
            -j.get("match_score", 0)
        ))

        return aligned_jobs if len(aligned_jobs) >= 5 else all_jobs

    return all_jobs

def user_content_profile(user, skills_list): #builds text blob with everything know about use
    user_skills = [us.skill.name for us in user.skills]
    saved = SavedJobs.query.filter_by(user_id=user.id).all()
    saved_skills = set()
    saved_texts = []

    for s in saved:
        desc = (s.job_description or "").lower()
        desc = " ".join(desc.split())
        skills_found = extract_skills_from_description(desc, skills_list)
        saved_skills.update(skills_found)
        saved_texts.append(f"{s.job_title or ''} {s.job_description or ''}")

    all_skills = list(set(user_skills) | saved_skills)

    parts = []
    
    parts.append(" ".join(all_skills))  
    if user.career_goal:
        parts.append(user.career_goal)
        parts.append(user.career_goal)
    parts.extend(saved_texts)
    parts.extend(saved_texts)

    profile_text = " ".join(parts).lower().strip()
    return all_skills, profile_text

@cache.memoize(timeout=1800) # ollama is used to generate 3 job titles similar to the career goal outlined by the user, allows for more recommendations
def get_synonyms(user_goal):
    prompt=f""""Give me 3 job titles that are similar to  "{user_goal}"Explicity return only a JSON array of strings,nothing else, no explanation,no label just job titles!"""

    try:
        response = ollama.chat(model='llama3.2:1b', messages=[{'role': 'user', 'content': prompt}])

        text= response['message']['content'].strip()
        synonyms=json.loads(text)
        return synonyms[:3]
    except Exception as e:
        print(f"Ollama error: {e}")
        return []

def search_query(user_goal, user_experience, user): # creates a list pf search quereies to send to reed api, allows for the generation of broader jobs
    queries = [user_goal]
    synonyms = get_synonyms(user_goal)
    queries.extend(synonyms)


    if user:
        saved = SavedJobs.query.filter_by(user_id=user.id).all()
        for s in saved[:3]:
            if s.job_title and s.job_title not in queries:
                queries.append(s.job_title)

    level = extract_experience_level(user_experience)
    if level != "Not specified":
        queries = [f"{level.lower()} {user_goal}"] + queries

    seen = set()
    unique = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique.append(q)
    return unique
    
def fetch_jobs(user_goal, user_experience, extra_params,user): #search the queries generated from search_query
    queries = search_query(user_goal, user_experience, user)
    seen_ids = set()
    all_jobs = []

    for query in queries[:4]:
        params = {**extra_params, "keywords": query, "resultsToTake": 20}
        try:
            data = job_fetch(tuple(sorted(params.items())))
            for job in data.get("results", []):
                job_id = job.get("jobId")
                if job_id not in seen_ids:
                    seen_ids.add(job_id)
                    all_jobs.append(job)
        except Exception as e:
            print(f"Query failed for '{query}': {e}")
            continue

    return all_jobs



@cache.memoize(timeout=200)
def get_similar_jobs(job_id, job_title): #generates jobs with same title as one user is viewing
    try:
        results = requests.get(
            f"{BASE_URL}/search",
            params={"keywords": job_title or "", "res": 6},
            auth=(API_KEY, ""),timeout=6).json().get("results", [])

        return [j for j in results if j.get("jobId") != job_id][:6] #returns 6 similar jobs ,different to the one the user is viewing

    except Exception as e:
        print(f"error: {e}")
        return []


def course_matches(course_skills,missing_skills): #checks if the missing skills is covered in by any course
    for skill in missing_skills:
        if skill.lower() in (course_skills).lower():
            return True
    return False

@cache.memoize(timeout=3600)
def get_courses(missing_skills_tuple): #shows courses that covers users missing skills for that job
    missing_skills = list(missing_skills_tuple)
    try:
        df = pd.read_csv('csv/courses.csv')
        matches = df['skills'].apply(course_matches, args=(missing_skills[:10],))
        return df[matches].head(5).to_dict('records')
    except Exception as e:
        print(f"Course error: {e}")
        return []


@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404


def skill_overlap_score(user_skills, job_skills): # calculates the percentage of the required skills the user has 
    userskill = set()
    for x in user_skills:
        if str(x).strip():
            userskill.add(str(x).strip().lower())

    jobskill = set()
    for x in job_skills:
        if str(x).strip():
            jobskill.add(str(x).strip().lower())

    if not jobskill:
        return 0.0
    return (len(userskill & jobskill) / len(jobskill)) * 100.0
    


def tfidf_cosine_score(user_profile_text, job_text): # compares two user profile to job description , uses cosine similarity
    if not user_profile_text or not job_text:
        return 0.0

    tfidf = TfidfVectorizer(stop_words="english")
    X = tfidf.fit_transform([user_profile_text, job_text])

    return cosine_similarity(X[0:1], X[1:2])[0][0] * 100


def calculate_match(combined_skills, profile_text, job_skills, job_desc, job_title): #final scoring algorithm
    
    skill_score = skill_overlap_score(combined_skills, job_skills)
    cosine_score = tfidf_cosine_score(profile_text, job_desc)
    title_score = tfidf_cosine_score(profile_text, job_title)
    
    return round(0.40 * skill_score + 0.4 * cosine_score + 0.20 * title_score, 2)

if __name__ == "__main__":
    app.run(debug=True)