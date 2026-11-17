package com.melkadlc;

import java.time.OffsetDateTime;

/** A short, server-verified grant measured against the monotonic Android clock. */
public final class LicenseLease {
    private static final long MAX_CHECK_AGE_MS = 45000;
    private final long verifiedAt;
    private final long expiresAt;
    public final String activationDate;
    public final String expirationDate;

    public LicenseLease(String status, String serverTime, String activated, String expiration,
                        long requestStartedAt) {
        if (!"active".equals(status) || requestStartedAt < 0) throw new IllegalArgumentException("inactive");
        long server = OffsetDateTime.parse(serverTime).toInstant().toEpochMilli();
        long end = OffsetDateTime.parse(expiration).toInstant().toEpochMilli();
        long start = OffsetDateTime.parse(activated).toInstant().toEpochMilli();
        long remaining = Math.subtractExact(end, server);
        if (remaining <= 0 || start > server || remaining > 315360000000L)
            throw new IllegalArgumentException("expired_or_invalid");
        verifiedAt = requestStartedAt;
        expiresAt = Math.addExact(requestStartedAt, remaining);
        activationDate = activated;
        expirationDate = expiration;
    }

    public boolean valid(long now) {
        return now >= verifiedAt && now < expiresAt && now-verifiedAt < MAX_CHECK_AGE_MS;
    }

    public long secondsLeft(long now) {
        return Math.max(0, (expiresAt-now)/1000);
    }
}
