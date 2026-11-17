package com.melkadlc;

public final class LicenseLeaseTest {
    private static void check(boolean condition) { if(!condition)throw new AssertionError(); }
    private static LicenseLease grant(String status,String end) {
        return new LicenseLease(status,"2026-11-17T12:00:00.123456+00:00",
            "2026-11-17T11:00:00Z",end,1000);
    }
    private static void rejected(String status,String end) {
        try {grant(status,end);throw new AssertionError("Invalid grant accepted");}
        catch(IllegalArgumentException expected){}
    }
    public static void main(String[] args) {
        LicenseLease valid=grant("active","2026-11-18T12:00:00.123456+00:00");
        check(valid.valid(1000)); check(valid.valid(45000));
        check(!valid.valid(46000)); check(!valid.valid(999));
        check(valid.secondsLeft(1000)==86400);
        LicenseLease shortGrant=grant("active","2026-11-17T12:00:01.123456+00:00");
        check(shortGrant.valid(1999));check(!shortGrant.valid(2000));
        rejected("available","2026-11-18T12:00:00Z");
        rejected("revoked","2026-11-18T12:00:00Z");
        rejected("suspended","2026-11-18T12:00:00Z");
        rejected("expired","2026-11-18T12:00:00Z");
        rejected("active","2026-11-17T12:00:00.123456+00:00");
        rejected("active","2026-11-17T10:00:00Z");
        System.out.println("LicenseLease: all security assertions passed");
    }
}
