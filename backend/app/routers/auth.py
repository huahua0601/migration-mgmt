from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.schemas import LoginRequest, TokenResponse, UserCreate, UserUpdate, UserPasswordUpdate, UserOut
from app.utils.auth import hash_password, verify_password, create_token, get_current_user, require_admin

router = APIRouter(prefix="/api/auth", tags=["Auth"])
user_router = APIRouter(prefix="/api/users", tags=["Users"])


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.password):
        raise HTTPException(status_code=401, detail="Wrong username or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    token = create_token(user.id, user.username, user.role)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.put("/password")
def change_password(req: UserPasswordUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(req.old_password, user.password):
        raise HTTPException(status_code=400, detail="Wrong old password")
    user.password = hash_password(req.new_password)
    db.commit()
    return {"msg": "ok"}


# ── User CRUD (admin) ──
@user_router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.query(User).order_by(User.id).all()


@user_router.post("", response_model=UserOut, status_code=201)
def create_user(req: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    u = User(username=req.username, password=hash_password(req.password), email=req.email, role=req.role)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@user_router.put("/{uid}", response_model=UserOut)
def update_user(uid: int, req: UserUpdate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    u = db.query(User).get(uid)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    for k, v in req.model_dump(exclude_unset=True).items():
        setattr(u, k, v)
    db.commit()
    db.refresh(u)
    return u


@user_router.delete("/{uid}")
def delete_user(uid: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    u = db.query(User).get(uid)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(u)
    db.commit()
    return {"msg": "deleted"}
