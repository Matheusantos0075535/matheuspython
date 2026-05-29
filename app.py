import os
import random
from datetime import datetime, date, timedelta
from functools import wraps

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "sobrioapp-dev-secret-change-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///sobriety.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    record_streak = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    entries = db.relationship("StreakEntry", backref="user", lazy=True, cascade="all, delete-orphan")
    milestones = db.relationship("Milestone", backref="user", lazy=True, cascade="all, delete-orphan")


class StreakEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    note = db.Column(db.Text, nullable=False)
    smoked_today = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "date"),)


class Milestone(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    days_count = db.Column(db.Integer, nullable=False)
    achieved_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_record = db.Column(db.Boolean, default=False)


class Friendship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), default="pending")  # pending | accepted
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Challenge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    creator_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default="active")  # active | finished
    winner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MILESTONE_DAYS = [1, 3, 7, 14, 21, 30, 60, 90, 180, 365]

MILESTONE_INFO = {
    1:   {"icon": "🌱", "name": "Primeira Semente",  "desc": "1 dia sem fumar!"},
    3:   {"icon": "🌿", "name": "Brotando",           "desc": "3 dias sem fumar!"},
    7:   {"icon": "🍀", "name": "Uma Semana",          "desc": "7 dias sem fumar!"},
    14:  {"icon": "🌻", "name": "Duas Semanas",        "desc": "14 dias sem fumar!"},
    21:  {"icon": "💪", "name": "Três Semanas",        "desc": "21 dias sem fumar!"},
    30:  {"icon": "🏆", "name": "Um Mês",              "desc": "30 dias sem fumar!"},
    60:  {"icon": "🥇", "name": "Dois Meses",          "desc": "60 dias sem fumar!"},
    90:  {"icon": "🎖️", "name": "Três Meses",         "desc": "90 dias sem fumar!"},
    180: {"icon": "💎", "name": "Seis Meses",          "desc": "180 dias sem fumar!"},
    365: {"icon": "👑", "name": "Um Ano",              "desc": "365 dias sem fumar!"},
}

MOTIVATIONAL_MESSAGES = [
    "Continue assim! Cada dia conta! 💪",
    "Você está no controle da sua vida! 🌟",
    "Mais um dia de vitória! 🏆",
    "A liberdade está cada vez mais próxima! 🕊️",
    "Você é mais forte do que pensa! 💎",
    "Cada dia sem fumar é uma conquista! 🎉",
    "Sua saúde agradece! ❤️",
    "O futuro que você quer está sendo construído agora! 🔨",
    "Orgulhe-se de cada dia limpo! ✨",
    "Você está reescrevendo a sua história! 📖",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def calculate_streak(user_id):
    """Return (current_streak, checked_in_today)."""
    today = date.today()
    entries = StreakEntry.query.filter_by(user_id=user_id).order_by(StreakEntry.date.desc()).all()

    if not entries:
        return 0, False

    entry_dict = {e.date: e for e in entries}
    checked_in_today = today in entry_dict

    # If today's entry is a relapse, streak = 0
    if checked_in_today and entry_dict[today].smoked_today:
        return 0, True

    # Start counting from today (if checked in) or yesterday
    check_date = today if checked_in_today else today - timedelta(days=1)

    # If yesterday has no entry and we haven't checked in today, streak is broken
    if not checked_in_today and check_date not in entry_dict:
        return 0, False

    streak = 0
    while check_date in entry_dict:
        entry = entry_dict[check_date]
        if entry.smoked_today:
            break
        streak += 1
        check_date -= timedelta(days=1)

    return streak, checked_in_today


def check_and_award_milestones(user_id, streak):
    """Award any unearned milestones and update personal record. Returns list of new awards."""
    new_awards = []
    user = db.session.get(User, user_id)

    for days in MILESTONE_DAYS:
        if streak >= days:
            existing = Milestone.query.filter_by(
                user_id=user_id, days_count=days, is_record=False
            ).first()
            if not existing:
                db.session.add(Milestone(user_id=user_id, days_count=days, is_record=False))
                new_awards.append(("milestone", days))

    if streak > user.record_streak:
        db.session.add(Milestone(user_id=user_id, days_count=streak, is_record=True))
        user.record_streak = streak
        new_awards.append(("record", streak))

    db.session.commit()
    return new_awards


def get_friendship(user_id, other_id):
    return Friendship.query.filter(
        db.or_(
            db.and_(Friendship.user_id == user_id, Friendship.friend_id == other_id),
            db.and_(Friendship.user_id == other_id, Friendship.friend_id == user_id),
        )
    ).first()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("index"))
        if not db.session.get(User, session["user_id"]):
            session.clear()
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Routes — auth
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html", active_tab="login")


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password_hash, password):
        session["user_id"] = user.id
        session["username"] = user.username
        return redirect(url_for("dashboard"))

    flash("Usuário ou senha incorretos.", "error")
    return render_template("index.html", active_tab="login")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("index.html", active_tab="register")

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not username or not email or not password:
        flash("Preencha todos os campos.", "error")
        return render_template("index.html", active_tab="register")

    if User.query.filter_by(username=username).first():
        flash("Nome de usuário já existe.", "error")
        return render_template("index.html", active_tab="register")

    if User.query.filter_by(email=email).first():
        flash("Email já cadastrado.", "error")
        return render_template("index.html", active_tab="register")

    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
    )
    db.session.add(user)
    db.session.commit()

    session["user_id"] = user.id
    session["username"] = user.username
    flash("Bem-vindo! Sua jornada começa agora! 🌱", "success")
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Routes — dashboard & check-in
# ---------------------------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    user = db.session.get(User, user_id)
    today = date.today()

    streak, checked_in_today = calculate_streak(user_id)
    record = user.record_streak

    today_entry = StreakEntry.query.filter_by(user_id=user_id, date=today).first()

    milestones = Milestone.query.filter_by(user_id=user_id, is_record=False).all()
    earned_milestone_days = {m.days_count for m in milestones}

    next_milestone = next((d for d in MILESTONE_DAYS if d not in earned_milestone_days), None)
    next_milestone_progress = 0
    if next_milestone:
        next_milestone_progress = min(int(streak / next_milestone * 100), 100)

    recent_entries = (
        StreakEntry.query.filter_by(user_id=user_id)
        .order_by(StreakEntry.date.desc())
        .limit(7)
        .all()
    )

    return render_template(
        "dashboard.html",
        user=user,
        streak=streak,
        record=record,
        checked_in_today=checked_in_today,
        today_entry=today_entry,
        earned_milestone_days=earned_milestone_days,
        milestone_info=MILESTONE_INFO,
        milestone_days=MILESTONE_DAYS,
        next_milestone=next_milestone,
        next_milestone_progress=next_milestone_progress,
        recent_entries=recent_entries,
        motivational=random.choice(MOTIVATIONAL_MESSAGES),
        today=today,
    )


@app.route("/checkin", methods=["POST"])
@login_required
def checkin():
    user_id = session["user_id"]
    today = date.today()

    if StreakEntry.query.filter_by(user_id=user_id, date=today).first():
        flash("Você já fez seu check-in hoje!", "info")
        return redirect(url_for("dashboard"))

    note = request.form.get("note", "").strip()
    smoked = request.form.get("smoked") == "yes"

    if not note:
        flash("Por favor, escreva sobre como foi seu dia.", "error")
        return redirect(url_for("dashboard"))

    db.session.add(StreakEntry(user_id=user_id, date=today, note=note, smoked_today=smoked))
    db.session.commit()

    if smoked:
        flash("Tudo bem, recomeços fazem parte da jornada. Você consegue! 💪", "info")
    else:
        streak, _ = calculate_streak(user_id)
        awards = check_and_award_milestones(user_id, streak)
        if awards:
            for kind, value in awards:
                if kind == "record":
                    flash(f"🎉 NOVO RECORDE PESSOAL! {value} dias sem fumar! Incrível!", "milestone")
                elif kind == "milestone" and value in MILESTONE_INFO:
                    info = MILESTONE_INFO[value]
                    flash(f"{info['icon']} Nova conquista desbloqueada: {info['name']}! {info['desc']}", "milestone")
        else:
            flash(f"✅ Check-in feito! {streak} {'dia' if streak == 1 else 'dias'} — continue assim!", "success")

    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Routes — history
# ---------------------------------------------------------------------------

@app.route("/history")
@login_required
def history():
    user_id = session["user_id"]
    entries = (
        StreakEntry.query.filter_by(user_id=user_id)
        .order_by(StreakEntry.date.desc())
        .all()
    )
    return render_template("history.html", entries=entries, today=date.today())


# ---------------------------------------------------------------------------
# Routes — profile
# ---------------------------------------------------------------------------

@app.route("/profile")
@login_required
def profile():
    user_id = session["user_id"]
    user = db.session.get(User, user_id)

    streak, _ = calculate_streak(user_id)

    milestones = Milestone.query.filter_by(user_id=user_id, is_record=False).order_by(Milestone.days_count).all()
    earned_milestone_days = {m.days_count for m in milestones}

    record_milestones = (
        Milestone.query.filter_by(user_id=user_id, is_record=True)
        .order_by(Milestone.days_count)
        .all()
    )

    total_entries = StreakEntry.query.filter_by(user_id=user_id).count()
    clean_days = StreakEntry.query.filter_by(user_id=user_id, smoked_today=False).count()

    return render_template(
        "profile.html",
        user=user,
        streak=streak,
        record=user.record_streak,
        milestones=milestones,
        earned_milestone_days=earned_milestone_days,
        milestone_info=MILESTONE_INFO,
        milestone_days=MILESTONE_DAYS,
        record_milestones=record_milestones,
        total_entries=total_entries,
        clean_days=clean_days,
    )


# ---------------------------------------------------------------------------
# Routes — friends
# ---------------------------------------------------------------------------

@app.route("/friends")
@login_required
def friends():
    user_id = session["user_id"]
    user = db.session.get(User, user_id)

    accepted = Friendship.query.filter(
        db.or_(
            db.and_(Friendship.user_id == user_id, Friendship.status == "accepted"),
            db.and_(Friendship.friend_id == user_id, Friendship.status == "accepted"),
        )
    ).all()

    friend_ids = [
        f.friend_id if f.user_id == user_id else f.user_id
        for f in accepted
    ]

    friends_data = []
    for fid in friend_ids:
        friend = db.session.get(User, fid)
        fstreak, _ = calculate_streak(fid)
        friends_data.append({"user": friend, "streak": fstreak, "record": friend.record_streak})
    friends_data.sort(key=lambda x: x["streak"], reverse=True)

    my_streak, _ = calculate_streak(user_id)
    leaderboard = [{"user": user, "streak": my_streak, "record": user.record_streak, "is_self": True}]
    leaderboard += [dict(f) for f in friends_data]
    leaderboard.sort(key=lambda x: x["streak"], reverse=True)

    pending_received_raw = Friendship.query.filter_by(friend_id=user_id, status="pending").all()
    pending_received = [
        {"request": req, "sender": db.session.get(User, req.user_id)}
        for req in pending_received_raw
    ]

    pending_sent = Friendship.query.filter_by(user_id=user_id, status="pending").all()
    pending_sent_data = [
        {"request": req, "receiver": db.session.get(User, req.friend_id)}
        for req in pending_sent
    ]

    challenges_raw = Challenge.query.filter(
        db.or_(Challenge.creator_id == user_id, Challenge.friend_id == user_id),
        Challenge.status == "active",
    ).all()

    challenges = []
    for c in challenges_raw:
        opponent_id = c.friend_id if c.creator_id == user_id else c.creator_id
        opponent = db.session.get(User, opponent_id)
        ostreak, _ = calculate_streak(opponent_id)
        challenges.append({
            "challenge": c,
            "opponent": opponent,
            "opponent_streak": ostreak,
            "my_streak": my_streak,
        })

    return render_template(
        "friends.html",
        user=user,
        friends_data=friends_data,
        leaderboard=leaderboard,
        pending_received=pending_received,
        pending_sent=pending_sent_data,
        challenges=challenges,
        my_streak=my_streak,
    )


@app.route("/add_friend", methods=["POST"])
@login_required
def add_friend():
    user_id = session["user_id"]
    username = request.form.get("username", "").strip()

    if not username:
        flash("Informe o nome de usuário.", "error")
        return redirect(url_for("friends"))

    friend = User.query.filter_by(username=username).first()
    if not friend:
        flash("Usuário não encontrado.", "error")
        return redirect(url_for("friends"))

    if friend.id == user_id:
        flash("Você não pode se adicionar como amigo.", "error")
        return redirect(url_for("friends"))

    if get_friendship(user_id, friend.id):
        flash("Solicitação já enviada ou vocês já são amigos.", "info")
        return redirect(url_for("friends"))

    db.session.add(Friendship(user_id=user_id, friend_id=friend.id, status="pending"))
    db.session.commit()
    flash(f"Solicitação enviada para {username}! 📨", "success")
    return redirect(url_for("friends"))


@app.route("/accept_friend/<int:friendship_id>")
@login_required
def accept_friend(friendship_id):
    user_id = session["user_id"]
    fs = db.session.get(Friendship, friendship_id)
    if not fs or fs.friend_id != user_id:
        flash("Ação não autorizada.", "error")
        return redirect(url_for("friends"))

    fs.status = "accepted"
    db.session.commit()
    sender = db.session.get(User, fs.user_id)
    flash(f"Você e {sender.username} agora são amigos! 🤝", "success")
    return redirect(url_for("friends"))


@app.route("/reject_friend/<int:friendship_id>")
@login_required
def reject_friend(friendship_id):
    user_id = session["user_id"]
    fs = db.session.get(Friendship, friendship_id)
    if not fs or fs.friend_id != user_id:
        flash("Ação não autorizada.", "error")
        return redirect(url_for("friends"))

    db.session.delete(fs)
    db.session.commit()
    flash("Solicitação recusada.", "info")
    return redirect(url_for("friends"))


@app.route("/create_challenge/<int:friend_id>", methods=["POST"])
@login_required
def create_challenge(friend_id):
    user_id = session["user_id"]

    fs = get_friendship(user_id, friend_id)
    if not fs or fs.status != "accepted":
        flash("Você só pode desafiar amigos.", "error")
        return redirect(url_for("friends"))

    existing = Challenge.query.filter(
        db.or_(
            db.and_(Challenge.creator_id == user_id, Challenge.friend_id == friend_id),
            db.and_(Challenge.creator_id == friend_id, Challenge.friend_id == user_id),
        ),
        Challenge.status == "active",
    ).first()
    if existing:
        flash("Já existe um desafio ativo com este amigo.", "info")
        return redirect(url_for("friends"))

    db.session.add(Challenge(creator_id=user_id, friend_id=friend_id, start_date=date.today()))
    db.session.commit()
    friend = db.session.get(User, friend_id)
    flash(f"Desafio criado com {friend.username}! Que ganhe o mais forte! ⚔️", "success")
    return redirect(url_for("friends"))


@app.route("/cancel_challenge/<int:challenge_id>")
@login_required
def cancel_challenge(challenge_id):
    user_id = session["user_id"]
    c = db.session.get(Challenge, challenge_id)
    if not c or (c.creator_id != user_id and c.friend_id != user_id):
        flash("Ação não autorizada.", "error")
        return redirect(url_for("friends"))

    db.session.delete(c)
    db.session.commit()
    flash("Desafio cancelado.", "info")
    return redirect(url_for("friends"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5000)
