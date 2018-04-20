# Import Statements
import os
import requests
import json
import re
from flask import jsonify
from flask import Flask, render_template, session, redirect, url_for, flash, request
from flask_script import Manager, Shell
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, FloatField, TextAreaField, IntegerField, BooleanField, SelectField, PasswordField, ValidationError
from wtforms.validators import Required, Length, Email, Regexp, EqualTo
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate, MigrateCommand
from api_key import api_key

# Imports for login management
from flask_login import LoginManager, login_required, logout_user, login_user, UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# Application configurations
app = Flask(__name__)
app.debug = True
app.use_reloader = True
app.config['SECRET_KEY'] = 'hardtoguessstring'
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get('DATABASE_URL') or "postgresql://localhost/SI364Finalroyoke"
app.config['SQLALCHEMY_COMMIT_ON_TEARDOWN'] = True
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# App addition setups
manager = Manager(app)
db = SQLAlchemy(app)
migrate = Migrate(app, db)
manager.add_command('db', MigrateCommand)

# Login configurations setup
login_manager = LoginManager()
login_manager.session_protection = 'strong'
login_manager.login_view = 'login'
login_manager.init_app(app)

########################
######## Models ########
########################

# Association table between a user and their playlist
user_playlist = db.Table('user_playlist',db.Column('track_id',db.Integer, db.ForeignKey('Track.id')),db.Column('playlist_id',db.Integer,db.ForeignKey('UserPlaylist.id')))

# User Model Class - special for logins
class User(UserMixin, db.Model):
    __tablename__ = 'User'
    id = db.Column(db.Integer,primary_key=True)
    username = db.Column(db.String(255), unique=True,index=True)
    email = db.Column(db.String(64), unique=True, index=True)
    password_hash = db.Column(db.String(128))
    user_playlist = db.relationship('UserPlaylist',backref='User')

    @property
    def password(self):
        raise AttributeError('password is not a readable attribute')

    @password.setter
    def password(self, password):
        self.password_hash = generate_password_hash(password)

    def verify_password(self, password):
        return check_password_hash(self.password_hash, password)

# DB load function
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Song class which will be added to playlists
class Track(db.Model):
    __tablename__ = 'Track'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128))
    artist = db.Column(db.Integer, db.ForeignKey('Artist.id'))
    rating = db.Column(db.Integer)
    

# Artist class
class Artist(db.Model):
	__tablename__ = 'Artist'
	id = db.Column(db.Integer, primary_key=True)
	name = db.Column(db.String(128))
	artist_songs = db.relationship('Track',backref='Artist')

# Playlist collection class
class UserPlaylist(db.Model):
	__tablename__ = 'UserPlaylist'
	id = db.Column(db.Integer,primary_key=True)
	name = db.Column(db.String(255))
	users_id = db.Column(db.Integer, db.ForeignKey('User.id'))

	# Setting up many to many relationship between playlist and songs (1 song may be in many playlists, 1 playlist may have many songs)
	songs = db.relationship('Track',secondary=user_playlist,backref=db.backref('UserPlaylist', lazy='dynamic'), lazy='dynamic')

########################
######## Forms #########
########################

# Form for a new user to create an account and register
class RegistrationForm(FlaskForm):
    email = StringField('Email:', validators=[Required(),Length(1,64),Email()])
    username = StringField('Username:',validators=[Required(),Length(1,64),Regexp('^[A-Za-z][A-Za-z0-9_.]*$',0,'Usernames must have only letters, numbers, dots or underscores')])
    password = PasswordField('Password:',validators=[Required(),EqualTo('password2',message="Passwords must match")])
    password2 = PasswordField("Confirm Password:",validators=[Required()])
    submit = SubmitField('Register User')

    def validate_email(self,field):
    	if User.query.filter_by(email=field.data).first():
            raise ValidationError('Email already registered.')

    def validate_username(self,field):
        if User.query.filter_by(username=field.data).first():
            raise ValidationError('Username already taken')

# Form for already registered users to login
class LoginForm(FlaskForm):
    email = StringField('Email', validators=[Required(), Length(1,64), Email()])
    password = PasswordField('Password', validators=[Required()])
    remember_me = BooleanField('Keep me logged in')
    submit = SubmitField('Log In')

# Flaskform to create a playlist
class CreatePlaylist(FlaskForm):
    name = StringField('Please enter the name of the playlist you would like to create: ',validators=[Required()])
    submit = SubmitField('Create')

    def validate_name(self,field):
        if UserPlaylist.query.filter_by(name=field.data, users_id=current_user.id).first():
            raise ValidationError('You have already created a playlist called {}'.format(field.data))

# Flaskform that prompts user to look up an artist
class ArtistLookupForm(FlaskForm):
	artist = StringField('Enter the name of the artist you want to learn more about: ', validators=[Required()])
	submit = SubmitField('Submit')

# Flaskform that prompts user to look up a track 
class TrackLookupForm(FlaskForm):
	track = StringField('What is the name of the song you want to learn more about? ', validators=[Required()])
	artist = StringField('What is the name of the artist whose song you are looking for? ',validators=[Required()])
	submit = SubmitField('Submit')

# Flaskform which will allow users to add songs to their playlists
class AddTrackForm(FlaskForm):
    playlist_pick = SelectField('Love this track? Add it to one of your playlists: ', validators=[Required()])
    rating = IntegerField('What rating would you give this song? ', validators=[Required()])
    submit = SubmitField('Add')



# Used to update rating
class UpdateButtonForm(FlaskForm):
    submit = SubmitField('Update Rating')

class UpdateInfoForm(FlaskForm):
    new_rating = IntegerField('What would you like the new rating of this song to be? ', validators=[Required()])
    submit = SubmitField('Update')

# Flaskform to delete song/playlist
class DeleteButtonForm(FlaskForm):
    submit = SubmitField('Delete')

########################
### Helper functions ###
########################
def get_top_tracks():
    base_url = 'http://ws.audioscrobbler.com/2.0/'
    data = requests.get(base_url+'?method=geo.gettoptracks&country=united states&api_key={}&format=json'.format(api_key))
    usable_data = json.loads(data.text)
    return usable_data['tracks']['track'][:10]

def get_artist_info(artist): # Will mak a request to the last.fm api and return information regarding artist
    params = {}
    base_url = 'http://ws.audioscrobbler.com/2.0/'
    params['method'] = 'artist.getinfo'
    params['artist'] = artist
    params['format'] = 'json'
    params['api_key'] = api_key
    try:
        request = requests.get(base_url, params=params)
        data = json.loads(request.text)
        summary = data['artist']['bio']['summary']
        summary = re.sub('<[^>]*>', '', summary)
        summary = summary.strip(summary[-10:])
        artist_name = artist
        image_url = data['artist']['image'][-3]['#text']
        similar_artists = [sim_artist['name'] for sim_artist in data['artist']['similar']['artist']]
        return (summary, artist_name, image_url, similar_artists)
    except:
        return False

def get_track_info(track,artist): # Will make a request to last.fm api and return information regarding a Track
    params = {}
    base_url = 'http://ws.audioscrobbler.com/2.0/'
    params['method'] = 'track.getinfo'
    params['artist'] = artist
    params['track'] = track
    params['format'] = 'json'
    params['api_key'] = api_key
    request = requests.get(base_url, params=params)
    data = json.loads(request.text)
    track_name = track
    artist_name = artist
    album_cover = data['track']['album']['image'][-2]['#text']
    try:
        summary = data['track']['wiki']['summary']
        summary = re.sub('<[^>]*>', '', summary)
        summary = summary.strip(summary[-11:])
    except:
        summary = 'There is no summary information for this track, sorry! The Last.fm page for the song can be found '
    return (summary,track_name,artist_name,album_cover)

def get_or_create_artist(artist): # Will add an artist to the Artist Model
    a = Artist.query.filter_by(name=artist).first()
    if a:
    	return a
    if not a:
    	a = Artist(name=artist)
    	db.session.add(a)
    	db.session.commit()
    	return a

def get_or_create_track(track,artist,rating): # Will add a track to the Track Model
    t = Track.query.filter_by(title=track).first()
    if t:
        t.rating = rating
        db.session.commit()
        return t
    else:
    	a = Artist.query.filter_by(name=artist).first()
    	t = Track(title=track,artist=a.id,rating=rating)
    	a.artist_songs.append(t)
    	db.session.add(t)
    	db.session.commit()
    	return t

def get_or_create_playlist(playlist): # Will add a playlist to the UserPlaylist Model
    p = UserPlaylist.query.filter_by(name=playlist, users_id = current_user.id).first()
    if p:
        flash('You already have a playlist called {}'.format(playlist))
        return p
    else:
        p = UserPlaylist(name=playlist, users_id = current_user.id)
        db.session.add(p)
        db.session.commit()
        flash('Playlist created!')
        return p

def add_track_to_playlist(track,artist,playlist,rating): # Will take a track and add it to the prexisting playlist indicated
    track_artist = get_or_create_artist(artist)
    new_track = get_or_create_track(track=track,artist=artist,rating=rating)
    new_playlist = UserPlaylist.query.filter_by(name=playlist, users_id = current_user.id).first()
    if new_track not in new_playlist.songs:
        new_playlist.songs.append(new_track)
        db.session.commit()
        flash('{} added to {} with a rating of {}'.format(track, playlist, rating))
        return new_playlist
    flash('{} added to {} with a rating of {}'.format(track, playlist, rating))
    return new_playlist


########################
#### View functions ####
########################

@app.errorhandler(404) # Wil render errorhandling form when a 404 error occurs and prompt users to go back to home page
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500) # Wil render errorhandling form when a 404 error occurs and prompt users to go back to home page
def internal_server_error(e):
    return render_template('500.html'), 500

@app.route('/login',methods=["GET","POST"]) # Should render a template asking users to input username and password to login
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user is not None and user.verify_password(form.password.data):
            login_user(user, form.remember_me.data)
            return redirect(request.args.get('next') or url_for('index'))
        flash('Invalid username or password.')
    return render_template('login.html',form=form)

@app.route('/logout') # Should render a template asking users to confirm their logout
@login_required
def logout():
    logout_user()
    flash('You have been logged out')
    return redirect(url_for('index'))

@app.route('/register',methods=["GET","POST"]) # Will render a template asking users for information (email, username, password) and register them an account, redirect to home page
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(email=form.email.data,username=form.username.data,password=form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('You may now login!')
        return redirect(url_for('login'))
    errors = [v for v in form.errors.values()]
    if len(errors) > 0:
        flash("ERRORS IN SUBMISSION FORM - " + str(errors))
    return render_template('register.html',form=form)

@app.route('/', methods=['GET', 'POST']) # Home page which will wender a template asking users to sign in/register as well as have links to addition pages in the application
def index():
    return render_template('index.html')

@app.route('/searchartist', methods=['GET', 'POST']) # A page which will render a template asking users to enter an artist name, then will redirect to a new page with info on the artist
@login_required
def search_artist():
    form = ArtistLookupForm()
    return render_template('artist_lookup.html', form=form)

@app.route('/artistresult', methods=['GET', 'POST'])
@login_required
def artist_result():
    artist = request.args['artist']
    if artist != '':
        try:
            results = get_artist_info(artist)
            if len(results[0]) > 0 and len(results[1]) > 0 and len(results[2]) > 0 and len(results[3]) > 0:
                return render_template('artist_results.html', results=results)
            else:
                flash('Sorry, we could not find the artist you are looking for - make sure your spelling and punctuation is correct!')
                return redirect(url_for('search_artist'))
        except:
            flash('Sorry, we could not find the artist you are looking for - make sure your spelling and punctuation is correct!')
            return redirect(url_for('search_artist'))
    else:
        flash('An artist name is required!')
        return redirect(url_for('search_artist'))


@app.route('/searchtrack', methods=['GET', 'POST']) # A page which will render a template asking users to enter an artist and track name, then will redirect to a new page with info on the track
@login_required
def search_track():
    form = TrackLookupForm()
    if form.validate_on_submit():
        track = form.track.data
        artist = form.artist.data
        try:
            results = get_track_info(track,artist)
            return render_template('track_results.html', results=results)
        except:
            flash('Sorry, we could not find the track you were lookinf for')
            return redirect(url_for('search_track'))
    errors = [v for v in form.errors.values()]
    if len(errors) > 0:
        flash("!!!! ERRORS IN FORM SUBMISSION - " + str(errors))
    return render_template('track_lookup.html',form = form)

@app.route('/createplaylist', methods=['GET', 'POST']) # A page which will render a template to ask a user the name of new playlist, redirect to all playlist page
@login_required
def create_playlist():
    form = CreatePlaylist()
    if request.method == 'POST':
        playlist_name = form.name.data
        get_or_create_playlist(playlist=playlist_name)
        return redirect(url_for('playlists'))
    return render_template('create_playlist.html',form=form)

@app.route('/playlists', methods=['GET', 'POST']) # A page which will show all playlists the user has created, with each playlist being clickable and deletable
@login_required
def playlists():
    form = DeleteButtonForm()
    playlists = UserPlaylist.query.filter_by(users_id=current_user.id).all()
    return render_template('playlists.html',playlists=playlists,form=form)

@app.route('/playlists/<id_num>') # A page for a specific playlist, that will have a list of all of the songs a user has added to the playlist 
def playlist_contents(id_num):
    form = UpdateButtonForm()
    id_num = int(id_num)
    playlist = UserPlaylist.query.filter_by(id=id_num).first()
    tracks = playlist.songs.all()
    artist_dict = {}
    for track in tracks:
        artist_dict[track.artist] = Artist.query.filter_by(id=track.artist).first().name
    return render_template('playlist.html', playlist=playlist,tracks=tracks,artist_dict=artist_dict,form=form)

@app.route('/add_track/<artist>/<track>', methods=['GET','POST'])
def adding_track(artist,track):
    form = AddTrackForm()
    all_playlists = UserPlaylist.query.filter_by(users_id=current_user.id).all()
    choices = [(p.id, p.name) for p in all_playlists]
    form.playlist_pick.choices = choices
    if request.method == 'POST':
        playlist_pick = form.playlist_pick.data
        rating = form.rating.data
        playlist = UserPlaylist.query.filter_by(id=playlist_pick,users_id=current_user.id).first().name
        add_track_to_playlist(track,artist,playlist,rating)
        return redirect(url_for('playlists'))
    return render_template('add_song.html',form=form)


@app.route('/delete/<lst>', methods=["GET","POST"]) # A page that will delete a selected playlist then will redirect to a page of all playlists (besides delete one)
@login_required
def delete_playlist(lst):
    p = UserPlaylist.query.filter_by(name=lst,users_id = current_user.id).first()
    db.session.delete(p)
    db.session.commit()
    flash('Deleted {} from your playlists!'.format(lst))
    return redirect(url_for('playlists'))

@app.route('/update/<song>',methods=["GET","POST"]) # A page used to update a song rating. Will redirect back to the playlist, but with the updated rating
@login_required
def update(song):
    form = UpdateInfoForm()
    if form.validate_on_submit():
        new_rating = form.new_rating.data
        t = Track.query.filter_by(title=song).first()
        t.rating = new_rating
        db.session.commit()
        flash('Updated rating of {}'.format(song))
        return redirect(url_for('playlists'))
    return render_template('update.html', form=form, song=song)

@app.route('/ajax')
def great_search():
    x = jsonify({'topsongs': [{'name': track['name']+' - '+track['artist']['name']} for track in get_top_tracks()]})
    return x

if __name__ == '__main__':
    db.create_all()
    manager.run()