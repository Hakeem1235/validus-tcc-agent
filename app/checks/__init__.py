"""The eight TCC checks. Each is a pure function Case -> CheckResult."""
from app.checks import bank_mandate, cob, distributor, identity, kyc, minor, referral, tpp

REGISTRY = {
    "FOLIO_IDENTITY": identity.run,
    "KYC_STATUS": kyc.run,
    "THIRD_PARTY_PAYMENT": tpp.run,
    "BANK_MANDATE": bank_mandate.run,
    "COB_COOLING": cob.run,
    "DISTRIBUTOR_CODE": distributor.run,
    "MINOR_RULES": minor.run,
    "REFERRAL": referral.run,
}
