/*
 * ����� ������ SMS-���������� ����������.
 *
 * �������: ��� ����, �� � ukrainian.h, �� ��������� cp1251 -- ���� ��� �����
 * HX8353E_charset_UA.h ������ ���� 192-255. �� �������� � UTF-8.
 *
 * ���� ������� ������, � �� ������ � stringsTable_t: SMS -- ������� ���� �����
 * �����, � ������� ����� ���� �� � ������ ����, ���� ���� CPS. ��� �������
 * ����� ���� ������� � �� ��������� � �'��� � ������� �������� ����� � ���Ͳ�
 * �����, ������� �����������. ��� ����������� ���������� �� ���� ���������.
 */
#ifndef USER_INTERFACE_LANGUAGES_MESSAGES_UA_H_
#define USER_INTERFACE_LANGUAGES_MESSAGES_UA_H_

#define MSGS_TITLE               "�����������"
#define MSGS_INBOX_FMT           "������ (%d)"
#define MSGS_SENT_FMT            "�������� (%d)"
#define MSGS_NEW                 "���� �����������"
#define MSGS_TITLE_SENT          "��������"
#define MSGS_TITLE_INBOX         "������"
#define MSGS_EMPTY               "(��������)"
#define MSGS_HINT_BACK           "RED:�����"
#define MSGS_DELETE_ALL          "[�������� ���]"
#define MSGS_TO                  "����"
#define MSGS_FROM                "³�"
#define MSGS_HINT_SENT_ITEM      "SK2+GRN:��� GRN:�� ���"
#define MSGS_HINT_INBOX_ITEM     "SK2+GRN:��� GRN:�����"
#define MSGS_TITLE_NEW           "���� �����������"
#define MSGS_CHARS_FMT           "%d/%d ����."
#define MSGS_HINT_PRESET         "U:������  L:������"
#define MSGS_HINT_TO_CANCEL      "GRN:����  RED:�����"
#define MSGS_TITLE_RCPT          "���������"
#define MSGS_TO_FMT              "����: %s"
#define MSGS_TYPE_FMT            "���: %s"
#define MSGS_GROUP               "�����"
#define MSGS_PRIVATE             "���������"
#define MSGS_HINT_ID             "0-9:id  L:������"
#define MSGS_HINT_GRP_PRIV       "U/D:�����/������"
#define MSGS_HINT_CONTACTS       "SK1:��������"
#define MSGS_HINT_SEND_BACK      "GRN:��������  RED:�����"
#define MSGS_TITLE_PICK_TG       "���� TG ��������"
#define MSGS_TITLE_PICK_PC       "���� PC ��������"
#define MSGS_NO_CONTACTS         "(���� ��������)"
#define MSGS_SENT_OK             "��������"
#define MSGS_KEYED_TX            "(����� � ����)"
#define MSGS_SEND_FAILED         "�� ��������"
#define MSGS_ERR_GENERIC         "�������"
#define MSGS_ERR_TX_BUSY         "TX ��������"
#define MSGS_ERR_BAD_TEXT        "������ �����"
#define MSGS_ERR_TOO_LONG        "�������� �����"
#define MSGS_FAIL_FMT            "%s (%d)"
#define MSGS_HINT_ANY_KEY        "����-��� ������: �����"
#define MSGS_MONITOR_FMT         "�������: %s"
#define MSGS_MON_ON              "����"
#define MSGS_MON_OFF             "����"
/* ����� ��������: ������ �� ������������, ��� ���������� (������� ��������). */
#define MSGS_MORE_UNREAD_FMT     "�� %d ��������."
#define MSGS_FOREIGN             " (�� ���)"
/* ����� TX SMS (Task #31, 2026-09-29). */
#define MSGS_TX_MODE_FMT         "TX: %s"
#define MSGS_TX_MODE_UNCONF      "\xC1\xE5\xE7 \xEF\xB3\xE4\xF2\xE2."
#define MSGS_TX_MODE_R12         "\xCF\xB3\xE4\xF2\xE2. \xBD"
#define MSGS_TX_MODE_R34         "\xCF\xB3\xE4\xF2\xE2. \xBE"

#endif /* USER_INTERFACE_LANGUAGES_MESSAGES_UA_H_ */
