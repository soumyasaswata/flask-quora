from main import celery,APP_ROOT
from main.models import User, Post, Answer
from flask import url_for, json, jsonify, send_file
# from flask_login import current_user
import time

@celery.task
def download_task(username):
    user = User.query.filter_by(username=username).first_or_404()
    posts = Post.query.filter_by(author=user).order_by(Post.date_posted.desc())
    posts = Post.query.filter_by(author=user).order_by(Post.date_posted.desc())

    url = APP_ROOT + '/static/'+username+'.txt'
    with open(url,'w') as file_data:
        user_data = []
        for post in posts:
            data = {
                "username" : post.author.username,
                "Question" : post.title,
                "Description" : post.content,
                "date_posted" : str(post.date_posted)
            }
            user_data.append(data)
        json.dump(user_data, file_data)
    return user_data