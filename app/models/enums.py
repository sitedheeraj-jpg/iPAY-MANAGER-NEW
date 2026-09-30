from enum import StrEnum


class Role(StrEnum):
    ADMIN = "Admin"
    AGENT = "Agent"
    USER = "User"


class AdminRole(StrEnum):
    OWNER = "Owner"
    ADMIN = "Admin"


class Status(StrEnum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class TransactionType(StrEnum):
    CREDIT = "Credit"
    DEBIT = "Debit"


class WithdrawalStatus(StrEnum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class TaskStatus(StrEnum):
    PENDING = "Pending"
    PROCESSING = "Processing"
    APPROVED = "Approved"
    REJECTED = "Rejected"