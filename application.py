#!/usr/bin/env python

from flask import Flask, flash, render_template, request, redirect, \
    url_for, jsonify
from functools import wraps
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database_setup import Base, Brand, Model, User

# Importing libraries to support oauth system
from flask import session as login_session
from flask import make_response
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import random
import string
import httplib2
import json
import requests

app = Flask(__name__)

CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Car Catalog Application"

engine = create_engine('sqlite:///data.db')
Base.metadata.bind = engine

DB = sessionmaker(bind=engine)
session = DB()


# OAuth Login System
@app.route('/login')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    # return "The current session state is %s" % login_session['state']
    return render_template('login/login.html', STATE=state)


# Third party OAuth sign in via Google
@app.route('/gconnect', methods=['POST'])
def gconnect():
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    code = request.data

    try:
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])

    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(
            json.dumps('Current user is already connected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()
    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    if getUserID(login_session['email']) is None:
        print "User currently doesn't exist: creating a new one..."
        createUser(login_session)
    else:
        print "User already exists, restablishing connection..."

    return render_template('login/login_success.html', info=login_session)


# Sign off the user
@app.route('/gdisconnect')
def gdisconnect():
    access_token = login_session.get('access_token')
    if access_token is None:
        print "Access Token is None"
        response = make_response(
            json.dumps('Current user not connected.'), 401)
        return response

    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % \
        login_session['access_token']
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    login_session.clear()

    brand = session.query(Brand).all()
    models = session.query(Model).order_by(Model.id.desc())
    flash("Successfully logged out!")
    return render_template('home/publicHome.html', brands=brand, models=models)


# Home Page
@app.route('/')
def main():
    brand = session.query(Brand).all()
    models = session.query(Model).order_by(Model.id.desc())
    if 'username' not in login_session:
        return render_template(
            'home/publicHome.html', brands=brand, models=models)
    else:
        user = getUserInfo(getUserID(login_session['email']))
        return render_template(
            'home/home.html', brands=brand, models=models, user=user)


# List models respective to the brand
@app.route('/<brand>')
def listModels(brand):
    carMakers = session.query(Brand).all()
    selectedBrand = session.query(Brand).filter_by(name=brand).one()
    models = session.query(Model).filter_by(brand_id=selectedBrand.id).all()

    # Check if a user is online
    if 'username' not in login_session:
        return render_template(
            'modelList/publicModels.html',
            brands=carMakers,
            models=models,
            brand=selectedBrand
        )
    # Loads page that is only available for logged in users
    elif getUserID(login_session['email']) is not selectedBrand.user.id:
        user = getUserInfo(getUserID(login_session['email']))
        return render_template(
            'modelList/models.html',
            brands=carMakers,
            models=models,
            brand=selectedBrand,
            user=user
        )
    # Loads page of the brand and models if the user is the brand creator
    else:
        user = getUserInfo(getUserID(login_session['email']))
        return render_template(
            'modelList/models_personal.html',
            brands=carMakers,
            models=models,
            brand=selectedBrand,
            user=user
        )


# Display detailed information of the model itself
@app.route('/<brand>/<model>')
def modelInfo(brand, model):
    data = session.query(Model).filter_by(name=model).one()

    if 'username' not in login_session:
        return render_template(
            'modelInfo/publicModelInfo.html', info=data
        )
    elif getUserID(login_session['email']) is not data.user.id:
        user = getUserInfo(getUserID(login_session['email']))
        return render_template(
            'modelInfo/modelInfo.html', info=data, user=user
        )
    else:
        user = getUserInfo(getUserID(login_session['email']))
        return render_template(
            'modelInfo/modelInfo_personal.html', info=data, user=user
        )


# Add new models to the catalog
@app.route('/new', methods=['GET', 'POST'])
def newModel():
    if 'username' not in login_session:
        flash("Please login to continue")
        return redirect('/login')

    if request.method == 'POST':
        user = getUserInfo(getUserID(login_session['email']))
        brandname = session.query(Brand).filter_by(
            name=request.form['brand']).all()
        print user.email
        print "\n"

        # Check to determine whether the brandname already exists
        if(len(brandname) == 1):
            print "BRAND NAME ALREADY EXISTS!!!"
            print "\n"
            brand = session.query(Brand).filter_by(
                name=request.form['brand']).one()
            newModel = Model(
                name=request.form['name'],
                description=request.form['description'],
                price=request.form['price'],
                category=request.form['category'],
                brand=brand,
                user=user
            )
            session.add(newModel)
            session.commit()
            return redirect(url_for("listModels", brand=brand.name))
        else:
            print "NEW BRAND!!!"
            print "\n"
            newBrand = Brand(
                name=request.form['brand'],
                user=user
            )
            session.add(newBrand)
            session.commit()

            newModel = Model(
                name=request.form['name'],
                description=request.form['description'],
                price=request.form['price'],
                category=request.form['category'],
                brand=newBrand,
                user=user
            )
            session.add(newModel)
            session.commit()

            return redirect(url_for("listModels", brand=newBrand.name))

    return render_template(
        'newModel.html'
    )


# Modify existing models that are respective to the creator
@app.route('/<brand>/<model>/edit', methods=['GET', 'POST'])
def editModel(brand, model):
    modelOwner = session.query(Model).filter_by(name=model).one().user
    data = session.query(Model).filter_by(name=model).one()

    if 'username' not in login_session:
        return redirect('/login')
    elif login_session['email'] != modelOwner.email:
        return render_template(
            'modelInfo/publicModelInfo.html', info=data
        )

    if request.method == 'POST':
        if request.form['name']:
            data.name = request.form['name']
            session.add(data)
            session.commit()
        elif request.form['description']:
            data.description = request.form['description']
            session.add(data)
            session.commit()
        elif request.form['price']:
            data.price = request.form['price']
            session.add(data)
            session.commit()
        elif request.form['category']:
            data.category = request.form['category']
            session.add(data)
            session.commit()
        return redirect(
            url_for('modelInfo', brand=data.brand, model=data.name))
    else:
        return render_template(
            'editModel.html', car=data
        )


# Allows creators to only delete their own items
@app.route('/<brand>/<model>/delete', methods=['GET', 'POST'])
def deleteModel(brand, model):
    toDelete = session.query(Model).filter_by(name=model).one()
    data = session.query(Brand).filter_by(name=brand).one()

    if 'username' not in login_session:
        return redirect('/login')
    elif login_session['email'] != toDelete.user.email:
        return redirect('/')
    else:
        if request.method == 'POST':
            session.delete(toDelete)
            session.commit()
            return redirect(url_for('listModels', brand=data.name))
        else:
            return render_template(
                "deleteModel.html", model_id=toDelete.id, item=toDelete
            )


# Deletes the brand and all associated models
@app.route('/<brand>/delete', methods=['GET', 'POST'])
def deleteBrand(brand):
    toDelete = session.query(Brand).filter_by(name=brand).one()
    data = session.query(Brand).filter_by(name=brand).one()

    if 'username' not in login_session:
        return redirect('/login')
    elif login_session['email'] != toDelete.user.email:
        return redirect('/')

    if request.method == 'POST':
        session.delete(toDelete)
        session.commit()
        return redirect(url_for('main'))
    else:
        return render_template(
            "deleteBrand.html", item=data
        )


# Display information in JSON format
@app.route('/<brand>/<model>/JSON')
def dataJSON(brand, model):
    data = session.query(Model).filter_by(name=model).all()
    return jsonify(Catalog=[i.serialize for i in data])


# Creates a new user
def createUser(login_session):
    newUser = User(
        name=login_session['username'],
        email=login_session['email'],
        picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    print "User " + newUser.name + " successfully created!"


# Function to get general user infomration
def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


# Function to retrieve user ID via email
def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except():
        return None


if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=8000)
