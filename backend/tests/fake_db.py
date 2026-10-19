"""
In-memory stand-in for the MySQL layer, used by the flow tests.

It answers the specific SQL statements issued by backend/app.py and
keeps a controllable clock so OTP expiry can be tested. It is NOT a
general SQL engine: it matches statements by their distinctive text.
"""



class FakeState:
    def __init__(self):
        self.now = 0  # minutes, controlled by the test
        self.users = {}
        self.requests = {}
        self.sc = {}
        self.ai = {}
        self.otps = []
        self.audit = []
        self.reviews = []
        self._otp_seq = 0

    def add_user(self, **row):
        self.users[row["user_id"]] = row


class FakeCursor:
    def __init__(self, state, dictionary=False):
        self.s = state
        self.dict = dictionary
        self._rows = []
        self.rowcount = 0

    def close(self):
        pass

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    # ------------------------------------------------------------
    def execute(self, sql, params=()):
        q = " ".join(sql.split()).lower()
        p = tuple(params or ())
        s = self.s
        self._rows = []
        self.rowcount = 0

        # ---------- inserts ----------
        if q.startswith("insert into phone_change_requests"):
            request_id, user_id, old_phone, new_phone, mentor_id, token_hash, ttl = p
            s.requests[request_id] = {
                "request_id": request_id,
                "user_id": user_id,
                "old_phone": old_phone,
                "new_phone": new_phone,
                "auth_status": "PENDING",
                "parent_verification_status": "PENDING",
                "status": "PENDING",
                "mentor_id": mentor_id,
                "parent_token_hash": token_hash,
                "parent_token_expires_at": s.now + ttl,
                "rejection_reason": None,
            }
            return

        if q.startswith("insert into security_context"):
            (rid, kd, ld, fl, pr, mfa, pcf, ltd, ts) = p
            s.sc[rid] = dict(known_device=kd, location_deviation=ld,
                             failed_login_count=fl, recent_password_reset=pr,
                             mfa_verified=mfa, phone_change_frequency=pcf,
                             login_time_deviation=ltd, trust_score=ts)
            return

        if q.startswith("insert into phone_change_otps"):
            rid, channel, code_hash, ttl = p
            s._otp_seq += 1
            s.otps.append(dict(otp_id=s._otp_seq, request_id=rid,
                               channel=channel, code_hash=code_hash,
                               expires_at=s.now + ttl, attempts=0,
                               max_attempts=3, locked=0, verified=0))
            return

        if q.startswith("insert into audit_logs"):
            rid, uid, actor, action, details = p
            s.audit.append(dict(request_id=rid, actor=actor, action=action))
            return

        if q.startswith("insert into ai_assessments"):
            rid, score, level, factors, version = p
            s.ai[rid] = dict(risk_score=score, risk_level=level,
                             risk_factors=factors, model_version=version)
            return

        if q.startswith("insert into mentor_reviews"):
            s.reviews.append(p)
            return

        # ---------- updates ----------
        if q.startswith("update phone_change_otps set attempts"):
            attempts, locked, otp_id = p
            for o in s.otps:
                if o["otp_id"] == otp_id:
                    o["attempts"], o["locked"] = attempts, locked
                    self.rowcount = 1
            return

        if "set verified = 1" in q:
            (otp_id,) = p
            for o in s.otps:
                if o["otp_id"] == otp_id:
                    o["verified"], o["code_hash"] = 1, None
                    self.rowcount = 1
            return

        if q.startswith("update phone_change_otps set locked = 1"):
            (rid,) = p
            for o in s.otps:
                if o["request_id"] == rid and not o["verified"]:
                    o["locked"], o["code_hash"] = 1, None
                    self.rowcount += 1
            return

        if q.startswith("update phone_change_otps set code_hash"):
            code_hash, ttl, rid, channel = p
            for o in s.otps:
                if (o["request_id"] == rid and o["channel"] == channel
                        and not o["verified"]):
                    o["code_hash"] = code_hash
                    o["expires_at"] = s.now + ttl
                    o["attempts"], o["locked"] = 0, 0
                    self.rowcount = 1
            return

        if q.startswith("update phone_change_requests set") and "auth_status = 'verified'" in q:
            (rid,) = p
            r = s.requests[rid]
            if r["auth_status"] != "VERIFIED":
                r["auth_status"] = "VERIFIED"
                r["parent_verification_status"] = "VERIFIED"
                self.rowcount = 1
            return

        if q.startswith("update phone_change_requests set") and "status = 'security_hold'" in q:
            (rid,) = p
            r = s.requests[rid]
            r["status"] = "SECURITY_HOLD"
            r["parent_token_expires_at"] = s.now
            return

        if q.startswith("update phone_change_requests set") and "status = 'cancelled'" in q:
            (rid,) = p
            r = s.requests[rid]
            r["status"] = "CANCELLED"
            r["parent_token_expires_at"] = s.now
            return

        if q.startswith("update phone_change_requests set") and "reviewed_at" in q:
            decision, reason, rid = p
            s.requests[rid]["status"] = decision
            s.requests[rid]["rejection_reason"] = reason
            return

        if q.startswith("update users set phone_number"):
            phone, uid = p
            s.users[uid]["phone_number"] = phone
            return

        # ---------- selects ----------
        if q.startswith("select name, email, parent_email, parent_phone, phone_number, mentor_id"):
            u = s.users.get(p[0])
            if u:
                self._rows = [dict(u)]
            return

        if q.startswith("select email from users"):
            u = s.users.get(p[0])
            if u:
                self._rows = [{"email": u["email"]}]
            return

        if q.startswith("select request_id from phone_change_requests where user_id"):
            hits = [r for r in s.requests.values()
                    if r["user_id"] == p[0] and r["status"] == "PENDING"]
            self._rows = [{"request_id": hits[0]["request_id"]}] if hits else []
            return

        if q.startswith("select known_device, location_deviation, failed_login_count"):
            sc = s.sc.get(p[0])
            if sc:
                self._rows = [dict(sc)]
            return

        if "from phone_change_requests p" in q and "parent_token_hash = %s" in q:
            tok = p[0]
            for r in s.requests.values():
                if r["parent_token_hash"] == tok:
                    u = s.users[r["user_id"]]
                    m = s.users.get(r["mentor_id"]) or {}
                    row = dict(r)
                    row.update(
                        token_valid=(r["parent_token_expires_at"] or -1) > s.now,
                        student_name=u["name"],
                        student_email=u["email"],
                        parent_email=u["parent_email"],
                        parent_phone=u["parent_phone"],
                        mentor_email=m.get("email"),
                    )
                    self._rows = [row]
            return

        if q.startswith("select otp_id, code_hash, verified, locked, attempts"):
            rid, channel = p
            for o in s.otps:
                if o["request_id"] == rid and o["channel"] == channel:
                    row = dict(o)
                    row["is_valid"] = o["expires_at"] > s.now
                    self._rows = [row]
            return

        if q.startswith("select channel, verified, locked, attempts") and "order by field" in q:
            self._rows = [
                {"channel": o["channel"], "verified": o["verified"],
                 "locked": o["locked"], "attempts": o["attempts"],
                 "is_valid": o["expires_at"] > s.now}
                for o in s.otps if o["request_id"] == p[0]
            ]
            return

        if q.startswith("select channel, verified from phone_change_otps"):
            self._rows = [{"channel": o["channel"], "verified": o["verified"]}
                          for o in s.otps if o["request_id"] == p[0]]
            return

        if q.startswith("select * from phone_change_requests where request_id"):
            r = s.requests.get(p[0])
            if r:
                self._rows = [dict(r)]
            return

        if q.startswith("select user_id, status from phone_change_requests where request_id"):
            r = s.requests.get(p[0])
            if r:
                self._rows = [{"user_id": r["user_id"], "status": r["status"]}]
            return

        if q.startswith("select risk_score") and "from ai_assessments" in q:
            return

        # ---------- fallback for scoring helpers ----------
        # Historical-event queries return zero/empty, so features are neutral.
        if self.dict:
            self._rows = []
        else:
            self._rows = [(0,)]


class FakeConnection:
    def __init__(self, state):
        self.s = state

    def cursor(self, dictionary=False):
        return FakeCursor(self.s, dictionary)

    def start_transaction(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass
