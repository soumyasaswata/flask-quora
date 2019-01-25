import os
import secrets
from PIL import Image
from flask import Flask, render_template, url_for, flash, redirect, request, abort, send_file, jsonify
from main import app, db, bcrypt, APP_ROOT
from main.forms import RegistrationForm, LoginForm, UpdateAccountForm, QuestionForm, AnswerForm
from main.models import User, Post, Answer
from flask_login import login_user, current_user, logout_user, login_required
from elasticsearch import Elasticsearch
from main import routes
import celery
import redis
import json
from main import download_user_data
from main.search import qustion_search

es = Elasticsearch()

@app.route('/question')
@app.route('/')
@app.route('/home')
def home():
    page = request.args.get('page', 1, type=int)
    questions = Post.query.order_by(Post.date_posted.desc()).paginate(page=page, per_page=10)
    return render_template('home.html', questions = questions)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user = User(username=form.username.data, email=form.email.data, password=hashed_password)
        db.session.add(user)
        db.session.commit()
        flash('Your account has beencreated! You are now able to log in', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', title='Register', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and bcrypt.check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('home'))
        else:
            flash('Log in Unsuccessful. Please check email and password', 'danger')
    return render_template('login.html', title='Login', form=form)

@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for('home'))

def save_picture(form_picture):
    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_picture.filename)
    picture_fn = random_hex + f_ext
    picture_path = os.path.join(app.root_path, 'static/profile_pics', picture_fn)
    output_size = (250, 250)
    resize_image = Image.open(form_picture)
    resize_image.thumbnail(output_size)
    resize_image.save(picture_path)
    return picture_fn

@app.route("/account", methods=['GET', 'POST'])
@login_required
def account():
    form = UpdateAccountForm()
    if form.validate_on_submit():
        if form.picture.data:
            picture_file = save_picture(form.picture.data)
            current_user.image_file = picture_file
        current_user.username = form.username.data
        current_user.email = form.email.data
        db.session.commit()
        flash('Your account has been updated!', 'success')
        return redirect(url_for('account'))
    elif request.method == 'GET':
        form.username.data = current_user.username
        form.email.data = current_user.email
    image_file = url_for('static', filename='profile_pics/' + current_user.image_file)
    return render_template('account.html', title='Account', image_file=image_file, form=form)

@app.route("/question/new", methods=['GET', 'POST'])
@login_required
def new_question():
    form = QuestionForm()
    if form.validate_on_submit():
        question = Post(title = form.title.data, content=form.content.data, author=current_user)      
        db.session.commit()
        flash('Your post has been created!', 'success')
        question = Post.query.filter_by(title = form.title.data, author=current_user).all()[-1]
        insert_data(question.title, question.id)
        return redirect(url_for('home'))
    return render_template('create_question.html', title='New Question', form=form, legend = 'Ask Question')


@app.route("/question/<int:post_id>")
def question(post_id):
    question = Post.query.get_or_404(post_id)
    return render_template('question.html', title=question.title, question=question)

@app.route("/question/<int:post_id>/update", methods = ['GET', 'POST'])
def update_question(post_id):
    question = Post.query.get_or_404(post_id)
    if question.author != current_user:
        abort(403)
    form = QuestionForm()
    if form.validate_on_submit():
        question.title = form.title.data
        question.content = form.content.data
        db.session.commit()
        flash('Your post has been updated!', 'success')
        return redirect(url_for('question', post_id=question.id))
    elif request.method == 'GET':
        form.title.data = question.title
        form.content.data = question.content
    return render_template('create_question.html', title='Update Question', form=form, legend = 'Update your question')

@app.route("/question/<int:post_id>/delete", methods = ['POST'])
def delete_question(post_id):
    question = Post.query.get_or_404(post_id)
    if question.author != current_user:
        abort(403)
    db.session.delete(question)
    db.session.commit()
    flash('Your post has deleted!', 'success')
    return redirect(url_for('home'))



@app.route("/question/<int:post_id>/answer", methods = ['GET', 'POST'])
def answer_post(post_id):
    if current_user.is_authenticated:
        question = Post.query.get_or_404(post_id)
        form = AnswerForm()
        if form.validate_on_submit():
            ans = Answer(answer=form.answer.data)
            ans.user_id = current_user.id
            ans.post_id = post_id
            db.session.add(ans)
            db.session.commit()
            flash('Your answer has been updated!', 'success')
            return redirect(url_for('question', post_id=question.id))
        return render_template('answer.html', title='Answer Post', form=form, legend = 'Answer this post...', post=question)
    else:
        return redirect(url_for('login'))

@app.route('/user/<string:username>')
def user_questions(username):
    page = request.args.get('page', 1, type=int)
    user = User.query.filter_by(username=username).first_or_404()
    questions = Post.query.filter_by(author=user)\
        .order_by(Post.date_posted.desc())\
        .paginate(page=page, per_page=10)
    return render_template('user_questions.html', questions = questions, user=user)


@app.route('/user/download/<string:username>', methods=['GET','POST'])
@login_required
def downloads(username):
    async_result = download_user_data.download_task.delay(username)
    return jsonify({}), 202, {'Location':url_for('task_status', task_id=async_result.id)}


@app.route('/task/<string:task_id>', methods=['GET'])
def task_status(task_id):
    result = download_user_data.download_task.AsyncResult(task_id)
    if result.ready():
        status = 'Ready'
    else:
        status = 'Pending'
    return jsonify({'data': status})

#for adding all the data to Elasticsearch
# @app.before_request
# def insert_data():
#     INDEX_NAME = 'input_data'
#     if not es.indices.exists(INDEX_NAME):
#         es.indices.create(INDEX_NAME)
#     query = Post.query.all()
#     id = 1
#     for index in range(len(query)):
#         body={
#             'title': query[index].title
#         }
#         es.index(index=INDEX_NAME,doc_type='title', id =id, body=body)
#         id +=1
#     return "Success"

def insert_data(title, id):
    INDEX_NAME = 'input_data'
    if not es.indices.exists(INDEX_NAME):
        es.indices.create(INDEX_NAME)
    body={
        'title': title
    }
    es.index(index=INDEX_NAME,doc_type='title', id =id, body=body)
    # return "Success"

@app.route('/search', methods = ['GET','POST'])
def search():
    if request.method =='POST':
       keyword = request.form['keyword']
       search_query = qustion_search(keyword)
       es.indices.refresh(index='input_data')
       resp = es.search(index='input_data', doc_type='title', body=search_query)
       return render_template('search.html', keyword=keyword, response=resp)
    return render_template('layout.html')