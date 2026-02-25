import re
import difflib
import html
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# ---------- Конфигурация путей ----------

BASE_DIR = Path(__file__).resolve().parent
KB_DIR = BASE_DIR / "БЗ"
AGENTS_DIR = BASE_DIR / "Сценарные агенты"
MAIN_DIR = BASE_DIR / "Главный промт"
MAIN_FALLBACK_FILE = BASE_DIR / "Основной промт.txt"


# ---------- Работа с файлами ----------

def get_main_prompt_path() -> Path:
    """
    Возвращает путь к файлу главного промта.
    Логика:
    1) Если существует папка "Главный промт" — берём первый .txt/.md файл в ней.
    2) Иначе используем "Основной промт.txt" в корне.
    """
    if MAIN_DIR.exists() and MAIN_DIR.is_dir():
        files = sorted(
            [p for p in MAIN_DIR.iterdir() if p.is_file()],
            key=lambda p: p.name.lower(),
        )
        if not files:
            raise FileNotFoundError('В папке "Главный промт" нет файлов')
        preferred = None
        for f in files:
            if f.suffix.lower() in {".txt", ".md"}:
                preferred = f
                break
        return preferred or files[0]

    if MAIN_FALLBACK_FILE.exists():
        return MAIN_FALLBACK_FILE

    raise FileNotFoundError(
        'Не найден ни каталог "Главный промт", ни файл "Основной промт.txt"'
    )


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def normalize_title_for_match(title: str) -> str:
    """
    Приводим строки к удобному виду для “фаззи”-поиска:
    - убираем двоеточия
    - сжимаем пробелы
    - приводим к lower
    """
    no_colon = title.replace(":", " ")
    collapsed = re.sub(r"\s+", " ", no_colon)
    return collapsed.strip().lower()


def find_kb_file_by_title(raw_title: str) -> Path | None:
    """
    Находит файл в папке БЗ по тексту вида "Правило 2: СОСТАВ ПОДДЕРЖИВАЮЩЕЙ УБОРКИ".
    Ищем начало имени файла, игнорируя двоеточие и регистр.
    """
    if not KB_DIR.exists():
        return None

    target = normalize_title_for_match(raw_title)

    for file in KB_DIR.iterdir():
        if not file.is_file():
            continue
        base = file.stem  # без .txt
        norm = normalize_title_for_match(base)
        if norm.startswith(target):
            return file

    return None


def find_agent_file_by_name(agent_name: str) -> Path | None:
    """
    Находит файл агента в папке "Сценарные агенты" по имени, например "cleaner_finance_handler".
    Ожидаемый формат файла: <имя>.txt
    """
    if not AGENTS_DIR.exists():
        return None

    candidates = [
        p for p in AGENTS_DIR.iterdir() if p.is_file()
    ]
    lower_target = agent_name.lower()

    # Сначала точное совпадение по имени файла без расширения
    for file in candidates:
        if file.stem.lower() == lower_target:
            return file

    # Потом более мягкий поиск по подстроке
    for file in candidates:
        if lower_target in file.stem.lower():
            return file

    return None


# ---------- Парсинг ссылок в главном промте ----------

LINK_PATTERN = re.compile(
    r'(Используй статью из БЗ:\s*"([^"]+)"|вызывай агента с именем\s*"([^"]+)")',
    re.IGNORECASE,
)


def parse_prompt_with_links(text: str):
    """
    Разбивает текст на сегменты:
    - {'type': 'text', 'text': ...}
    - {'type': 'kb', 'title': ...}
    - {'type': 'agent', 'name': ...}
    """
    segments = []
    last_idx = 0

    for match in LINK_PATTERN.finditer(text):
        start, end = match.span()
        if start > last_idx:
            segments.append({"type": "text", "text": text[last_idx:start]})

        kb_title = match.group(2)
        agent_name = match.group(3)

        if kb_title:
            segments.append({"type": "kb", "title": kb_title, "full_match": match.group(0)})
        elif agent_name:
            segments.append({"type": "agent", "name": agent_name, "full_match": match.group(0)})

        last_idx = end

    if last_idx < len(text):
        segments.append({"type": "text", "text": text[last_idx:]})

    return segments


# ---------- Diff "Было / Стало" ----------

def make_diff_html(old: str, new: str) -> str:
    """
    Возвращает HTML-таблицу diff (слева "Было", справа "Стало") в стиле git.
    """
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff = difflib.HtmlDiff(wrapcolumn=80)
    table = diff.make_table(
        old_lines,
        new_lines,
        fromdesc="Было",
        todesc="Стало",
        context=True,
        numlines=3,
    )
    # Небольшая обёртка с кастомными стилями
    style = """
    <style>
    table.diff {font-family: monospace; font-size: 13px; border-collapse: collapse;}
    .diff_header {background: #f3f4f6; padding: 4px;}
    .diff_next {background: #e5e7eb;}
    .diff_add {background: #e6ffed;}
    .diff_chg {background: #fff5b1;}
    .diff_sub {background: #ffeef0;}
    td, th {padding: 2px 4px; border: 1px solid #e5e7eb;}
    </style>
    """
    return style + table


# ---------- Инициализация session_state ----------

if "active_file_path" not in st.session_state:
    st.session_state.active_file_path = None
if "active_file_label" not in st.session_state:
    st.session_state.active_file_label = None
if "original_content" not in st.session_state:
    st.session_state.original_content = ""
if "edited_content" not in st.session_state:
    st.session_state.edited_content = ""


def open_file_in_editor(path: Path, label: str):
    st.session_state.active_file_path = str(path)
    st.session_state.active_file_label = label
    content = read_text_file(path)
    st.session_state.original_content = content
    st.session_state.edited_content = content


# ---------- UI ----------

st.set_page_config(page_title="Промты и БЗ агента", layout="wide")
st.title("Управление промтами и БЗ агента")

# --- Главный промт ---

try:
    main_path = get_main_prompt_path()
    main_text = read_text_file(main_path)
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

col_main, col_buttons = st.columns([4, 1])

with col_main:
    st.subheader("Главный промт (просмотр)")
    segments = parse_prompt_with_links(main_text)

    # Рендерим текст построчно с кнопками-ссылками
    # Для простоты выводим всё в одном большом markdown-блоке + отдельные кнопки рядом.
    buffer = []
    link_buttons = []

    for idx, seg in enumerate(segments):
        if seg["type"] == "text":
            buffer.append(seg["text"])
        elif seg["type"] == "kb":
            # Сохраняем индекс для отрисовки кнопок
            placeholder = f"[БЗ:{idx}]"
            buffer.append(placeholder)
            link_buttons.append(("kb", idx, seg["title"], placeholder))
        elif seg["type"] == "agent":
            placeholder = f"[AGENT:{idx}]"
            buffer.append(placeholder)
            link_buttons.append(("agent", idx, seg["name"], placeholder))

    full_text_with_placeholders = "".join(buffer)

    # Показываем текст с подчёркнутыми плейсхолдерами как подсказку
    display_text = full_text_with_placeholders
    for kind, idx, title, placeholder in link_buttons:
        if kind == "kb":
            label = f'Используй статью из БЗ: "{title}"'
        else:
            label = f'вызывай агента с именем "{title}"'

        # Подсветка ссылок (визуально), клики — через отдельные кнопки
        link_html = (
            f'<span style="color:#2563eb; text-decoration:underline;">'
            f'{html.escape(label)}</span>'
        )
        display_text = display_text.replace(placeholder, link_html)

    st.markdown(display_text.replace("\n", "  \n"), unsafe_allow_html=True)

with col_buttons:
    st.subheader("Действия")
    if st.button("Редактировать главный промт"):
        open_file_in_editor(main_path, f"Главный промт: {main_path.name}")
    st.caption("Ссылки внутри текста ниже кликаются отдельными кнопками.")

    st.markdown("---")
    st.markdown("**Переход по ссылкам в тексте:**")
    for kind, idx, title, placeholder in link_buttons:
        if kind == "kb":
            btn_label = f'Открыть БЗ: "{title}"'
            if st.button(btn_label, key=f"kb_{idx}"):
                kb_file = find_kb_file_by_title(title)
                if kb_file is None:
                    st.warning(f'Не найден файл в БЗ для "{title}"')
                else:
                    open_file_in_editor(kb_file, f"БЗ: {kb_file.name}")
        else:
            btn_label = f'Открыть агента: "{title}"'
            if st.button(btn_label, key=f"agent_{idx}"):
                agent_file = find_agent_file_by_name(title)
                if agent_file is None:
                    st.warning(f'Не найден файл агента для "{title}"')
                else:
                    open_file_in_editor(agent_file, f"Агент: {agent_file.name}")


# --- Сайдбар: редактор + diff ---

st.sidebar.header("Редактор файла")

if st.session_state.active_file_path is None:
    st.sidebar.info("Выберите ссылку в тексте или нажмите 'Редактировать главный промт'.")
else:
    path = Path(st.session_state.active_file_path)
    st.sidebar.subheader(st.session_state.active_file_label or path.name)

    edited = st.sidebar.text_area(
        "Текст файла",
        value=st.session_state.edited_content,
        height=400,
        key="editor_text_area",
    )
    st.session_state.edited_content = edited

    if edited != st.session_state.original_content:
        st.sidebar.markdown("### Предпросмотр изменений (diff)")
        diff_html = make_diff_html(st.session_state.original_content, edited)
        components.html(diff_html, height=400, scrolling=True)

        if st.sidebar.button("Подтвердить и сохранить"):
            write_text_file(path, edited)
            st.session_state.original_content = edited
            st.sidebar.success("Изменения сохранены.")
    else:
        st.sidebar.info("Изменений нет.")