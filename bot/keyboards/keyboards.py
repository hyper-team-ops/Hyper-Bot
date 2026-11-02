from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

CHECK_AVAILABILITY = "الاستعلام عن وجود كورس أو تطبيق"
DOWNLOAD_REQUEST = "إرسال طلب تحميل"
TEAM_INFO = "حول الفريق"
COMPLAINT = "شكاوي واقتراحات"

MAIN_LAYOUT = [[CHECK_AVAILABILITY], [DOWNLOAD_REQUEST], [TEAM_INFO, COMPLAINT]]


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(MAIN_LAYOUT, resize_keyboard=True, one_time_keyboard=False)


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("إرسال رسالة إتمام طلب", callback_data="admin:finish")],
        [InlineKeyboardButton("إرسال رسالة", callback_data="admin:message")],
    ])
