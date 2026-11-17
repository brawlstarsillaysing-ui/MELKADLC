BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 01a0afe0bf7e

CREATE TABLE admin_audit_logs (
    admin_id BIGINT NOT NULL, 
    action VARCHAR(80) NOT NULL, 
    target VARCHAR(100) NOT NULL, 
    detail JSON NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_admin_audit_logs_admin_id ON admin_audit_logs (admin_id);

CREATE TABLE admin_operations (
    admin_id BIGINT NOT NULL, 
    request_key VARCHAR(100) NOT NULL, 
    input_hash VARCHAR(64) NOT NULL, 
    result JSON NOT NULL, 
    PRIMARY KEY (admin_id, request_key)
);

CREATE TABLE admin_users (
    user_id BIGINT NOT NULL, 
    active BOOLEAN NOT NULL, 
    PRIMARY KEY (user_id)
);

CREATE TABLE application_settings (
    key VARCHAR(80) NOT NULL, 
    value TEXT NOT NULL, 
    PRIMARY KEY (key)
);

CREATE TABLE broadcasts (
    admin_id BIGINT NOT NULL, 
    text VARCHAR(4000) NOT NULL, 
    media_type VARCHAR(10), 
    file_id VARCHAR(512), 
    button_text VARCHAR(80), 
    button_url VARCHAR(512), 
    status VARCHAR(16) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE promo_codes (
    code VARCHAR(40) NOT NULL, 
    reward_type VARCHAR(20) NOT NULL, 
    value NUMERIC(14, 2) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    max_uses INTEGER NOT NULL, 
    per_user_limit INTEGER NOT NULL, 
    uses INTEGER NOT NULL, 
    active BOOLEAN NOT NULL, 
    allowed_users JSON NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CHECK (reward_type IN ('balance','license','extension','discount')), 
    CHECK (uses >= 0 AND uses <= max_uses), 
    CHECK (value > 0 AND max_uses > 0 AND per_user_limit > 0), 
    UNIQUE (code)
);

CREATE TABLE rate_buckets (
    bucket VARCHAR(100) NOT NULL, 
    hits INTEGER NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (bucket)
);

CREATE INDEX ix_rate_buckets_expires_at ON rate_buckets (expires_at);

CREATE TABLE subscription_plans (
    id VARCHAR(36) NOT NULL, 
    name VARCHAR(80) NOT NULL, 
    duration_seconds INTEGER NOT NULL, 
    price NUMERIC(14, 2) NOT NULL, 
    active BOOLEAN NOT NULL, 
    PRIMARY KEY (id), 
    CHECK (price > 0 AND duration_seconds > 0)
);

CREATE TABLE users (
    id BIGINT NOT NULL, 
    username VARCHAR(64), 
    banned BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE broadcast_deliveries (
    broadcast_id VARCHAR(36) NOT NULL, 
    user_id BIGINT NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    PRIMARY KEY (broadcast_id, user_id), 
    FOREIGN KEY(broadcast_id) REFERENCES broadcasts (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE licenses (
    user_id BIGINT NOT NULL, 
    key_hash VARCHAR(64) NOT NULL, 
    key_ciphertext TEXT NOT NULL, 
    kind VARCHAR(16) NOT NULL, 
    duration_seconds INTEGER NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    activated_at TIMESTAMP WITH TIME ZONE, 
    expires_at TIMESTAMP WITH TIME ZONE, 
    device_limit INTEGER NOT NULL, 
    resets INTEGER NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CHECK (kind IN ('trial','paid','grant','promo')), 
    CHECK (status IN ('available','active','suspended','revoked')), 
    CHECK (duration_seconds > 0 AND device_limit BETWEEN 1 AND 100 AND resets >= 0), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    UNIQUE (key_hash)
);

CREATE INDEX ix_license_owner_kind ON licenses (user_id, kind);

CREATE INDEX ix_licenses_expires_at ON licenses (expires_at);

CREATE INDEX ix_licenses_user_id ON licenses (user_id);

CREATE TABLE payment_requests (
    user_id BIGINT NOT NULL, 
    amount NUMERIC(14, 2) NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    request_key VARCHAR(100) NOT NULL, 
    decided_at TIMESTAMP WITH TIME ZONE, 
    decided_by BIGINT, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CHECK (status IN ('pending','confirmed','rejected')), 
    CHECK (amount > 0), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    UNIQUE (user_id, request_key)
);

CREATE INDEX ix_payment_requests_user_id ON payment_requests (user_id);

CREATE TABLE promo_redemptions (
    promo_id VARCHAR(36) NOT NULL, 
    user_id BIGINT NOT NULL, 
    request_key VARCHAR(100) NOT NULL, 
    consumed BOOLEAN NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(promo_id) REFERENCES promo_codes (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    UNIQUE (user_id, request_key)
);

CREATE INDEX ix_promo_redemptions_promo_id ON promo_redemptions (promo_id);

CREATE INDEX ix_promo_redemptions_user_id ON promo_redemptions (user_id);

CREATE TABLE referrals (
    user_id BIGINT NOT NULL, 
    inviter_id BIGINT NOT NULL, 
    PRIMARY KEY (user_id), 
    CHECK (user_id != inviter_id), 
    FOREIGN KEY(inviter_id) REFERENCES users (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_referrals_inviter_id ON referrals (inviter_id);

CREATE TABLE support_tickets (
    user_id BIGINT NOT NULL, 
    subject VARCHAR(4000) NOT NULL, 
    file_id VARCHAR(512), 
    status VARCHAR(16) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_support_tickets_user_id ON support_tickets (user_id);

CREATE TABLE trial_entitlements (
    user_id BIGINT NOT NULL, 
    issued INTEGER NOT NULL, 
    PRIMARY KEY (user_id), 
    CHECK (issued >= 0 AND issued <= 5), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE user_settings (
    user_id BIGINT NOT NULL, 
    language VARCHAR(2) NOT NULL, 
    PRIMARY KEY (user_id), 
    CHECK (language IN ('ru','uk','en')), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE wallet_transactions (
    user_id BIGINT NOT NULL, 
    cash_delta NUMERIC(14, 2) NOT NULL, 
    bonus_delta NUMERIC(14, 2) NOT NULL, 
    debt_delta NUMERIC(14, 2) NOT NULL, 
    event VARCHAR(150) NOT NULL, 
    reason VARCHAR(500) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    UNIQUE (event)
);

CREATE INDEX ix_wallet_transactions_user_id ON wallet_transactions (user_id);

CREATE TABLE wallets (
    user_id BIGINT NOT NULL, 
    cash NUMERIC(14, 2) NOT NULL, 
    bonus NUMERIC(14, 2) NOT NULL, 
    bonus_debt NUMERIC(14, 2) NOT NULL, 
    PRIMARY KEY (user_id), 
    CHECK (cash >= 0 AND bonus >= 0 AND bonus_debt >= 0), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE device_bindings (
    license_id VARCHAR(36) NOT NULL, 
    device_hash VARCHAR(64) NOT NULL, 
    token_hash VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(license_id) REFERENCES licenses (id), 
    UNIQUE (license_id, device_hash), 
    UNIQUE (token_hash)
);

CREATE INDEX ix_device_bindings_license_id ON device_bindings (license_id);

CREATE TABLE license_activations (
    license_id VARCHAR(36) NOT NULL, 
    device_hash VARCHAR(64), 
    action VARCHAR(100) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(license_id) REFERENCES licenses (id)
);

CREATE INDEX ix_license_activations_license_id ON license_activations (license_id);

CREATE TABLE payment_evidence (
    payment_id VARCHAR(36) NOT NULL, 
    file_id VARCHAR(512) NOT NULL, 
    media_type VARCHAR(20) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(payment_id) REFERENCES payment_requests (id), 
    UNIQUE (payment_id, file_id)
);

CREATE INDEX ix_payment_evidence_payment_id ON payment_evidence (payment_id);

CREATE TABLE purchases (
    user_id BIGINT NOT NULL, 
    plan_id VARCHAR(36) NOT NULL, 
    license_id VARCHAR(36) NOT NULL, 
    amount NUMERIC(14, 2) NOT NULL, 
    cash_spent NUMERIC(14, 2) NOT NULL, 
    bonus_spent NUMERIC(14, 2) NOT NULL, 
    request_key VARCHAR(100) NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CHECK (amount = cash_spent + bonus_spent AND amount >= 0), 
    FOREIGN KEY(license_id) REFERENCES licenses (id), 
    FOREIGN KEY(plan_id) REFERENCES subscription_plans (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    UNIQUE (license_id), 
    UNIQUE (user_id, request_key)
);

CREATE INDEX ix_purchases_user_id ON purchases (user_id);

CREATE TABLE subscriptions (
    license_id VARCHAR(36) NOT NULL, 
    starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    ends_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (license_id), 
    FOREIGN KEY(license_id) REFERENCES licenses (id)
);

CREATE INDEX ix_subscriptions_ends_at ON subscriptions (ends_at);

CREATE TABLE support_messages (
    ticket_id VARCHAR(36) NOT NULL, 
    author_id BIGINT NOT NULL, 
    text VARCHAR(4000) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(ticket_id) REFERENCES support_tickets (id)
);

CREATE INDEX ix_support_messages_ticket_id ON support_messages (ticket_id);

CREATE TABLE referral_rewards (
    purchase_id VARCHAR(36) NOT NULL, 
    user_id BIGINT NOT NULL, 
    amount NUMERIC(14, 2) NOT NULL, 
    reversed BOOLEAN NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(purchase_id) REFERENCES purchases (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    UNIQUE (purchase_id)
);

CREATE INDEX ix_referral_rewards_user_id ON referral_rewards (user_id);

INSERT INTO alembic_version (version_num) VALUES ('01a0afe0bf7e') RETURNING alembic_version.version_num;

COMMIT;

