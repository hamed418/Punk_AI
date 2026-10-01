import enum
class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"
    super_admin = "super_admin"

class CampaignStatus(str, enum.Enum):
    draft = "draft"
    pending_approval = "pending_approval"
    approved = "approved"
    # Objects exist in Meta. "approved" only means the user accepted the plan —
    # without this every published campaign stayed indistinguishable from one
    # that was never sent, for the whole life of the row.
    published = "published"
    archived = "archived"


class AdPlatform(str, enum.Enum):
    google = "google"
    meta = "meta"
    both = "both"


class ConversationStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    archived = "archived"

class PurchaseType(str, enum.Enum):
    SUBSCRIPTION = "SUBSCRIPTION"
    TOKEN_PACK = "TOKEN_PACK"

class SubscriptionStatus(str, enum.Enum):
    active = "active"
    trialing = "trialing"
    past_due = "past_due"
    canceled = "canceled"
    unpaid = "unpaid"
    incomplete = "incomplete"
    incomplete_expired = "incomplete_expired"
    paused = "paused"
    free = "free"
    complete = "complete"
    paid = "paid"
class SubscriptionPaymentStatus(str, enum.Enum):
    active = "active"
    trialing = "trialing"
    past_due = "past_due"
    canceled = "canceled"
    unpaid = "unpaid"
    incomplete = "incomplete"
    incomplete_expired = "incomplete_expired"
    paused = "paused"
    free = "free"
    complete = "complete"
    paid = "paid"

class FAQCategoryType(str, enum.Enum):
    faq = "faq"
    support = "support"
    both = "both"

class SupportStatus(str, enum.Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"