import streamlit as st
import pandas as pd
from agent_backend import get_agent_configuration, run_scraping_job

# --- Page Configuration ---
st.set_page_config(page_title="Agentic News Reader", layout="wide", page_icon="📰")

# --- Custom CSS ---
st.markdown("""
<style>
    .card {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #e5e7eb;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        margin-bottom: 20px;
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    .news-title {
        font-size: 18px;
        font-weight: 700;
        color: #111827;
        margin-bottom: 10px;
        line-height: 1.4;
    }
    .news-desc {
        font-size: 14px;
        color: #4b5563;
        margin-bottom: 15px;
        display: -webkit-box;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .news-meta {
        font-size: 12px;
        color: #9ca3af;
        margin-top: auto;
    }
    .stButton>button {
        width: 100%;
        border-radius: 6px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# --- Session State ---
if 'articles' not in st.session_state:
    st.session_state.articles = []
if 'view_mode' not in st.session_state:
    st.session_state.view_mode = 'dashboard'
if 'current_article' not in st.session_state:
    st.session_state.current_article = None

# --- Helpers ---
def clean_title(item):
    """Fallback logic to ensure every card has a title"""
    if item.get('title'):
        return item.get('title')
    # If no title, use the last part of the URL
    url = item.get('url', 'Unknown')
    return url.split('/')[-1].replace('-', ' ').title()

# --- UI Logic ---
def show_dashboard():
    st.title("📰 AI News Agent")
    st.markdown("Enter a news site. The Agent will use **Playwright** to render the page and extract the latest stories.")

    with st.form("search_form"):
        col1, col2 = st.columns([4, 1])
        with col1:
            user_query = st.text_input("News Source", placeholder="e.g., [https://techcrunch.com](https://techcrunch.com) or 'Latest BBC World News'")
        with col2:
            submitted = st.form_submit_button("Fetch News")

    if submitted and user_query:
        # Clear previous results
        st.session_state.articles = []
        
        with st.status("🤖 AI Agent Working...", expanded=True) as status:
            st.write("🧠 Interpreting request & configuring crawler...")
            config = get_agent_configuration(user_query)
            
            if config:
                st.write(f"🌍 Target: `{config.get('startUrls')[0]['url']}`")
                st.write(f"🕷️ Strategy: Parsing with Playwright (Browser Mode)")
                
                results = run_scraping_job(config)
                st.session_state.articles = results
                
                count = len(results)
                status.update(label=f"✅ Done! Found {count} pages.", state="complete", expanded=False)
            else:
                status.update(label="❌ Configuration failed.", state="error")

    # --- Results Area ---
    if st.session_state.articles:
        st.divider()
        
        # Filter out items that are likely just the homepage itself or have no meaningful content
        valid_articles = [
            a for a in st.session_state.articles 
            if a.get('url') and len(a.get('markdown', '')) > 200
        ]
        
        st.subheader(f"Top Stories ({len(valid_articles)})")
        
        if len(valid_articles) == 0:
            st.warning("Scraper finished but found no substantive articles. Try a more specific URL (e.g. '[cnn.com/world](https://cnn.com/world)' instead of 'cnn.com').")
            with st.expander("Debug: See Raw Scraper Output"):
                st.json(st.session_state.articles)
        else:
            # Grid Layout
            cols = st.columns(3)
            for idx, article in enumerate(valid_articles):
                with cols[idx % 3]:
                    title = clean_title(article)
                    desc = article.get('description') or article.get('markdown')[:150] or "No preview available."
                    
                    with st.container():
                        st.markdown(f"""
                        <div class="card">
                            <div class="news-title">{title}</div>
                            <div class="news-desc">{desc}...</div>
                            <div class="news-meta">{article.get('url')}</div>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        if st.button(f"Read Article", key=f"read_{idx}"):
                            st.session_state.current_article = article
                            st.session_state.view_mode = 'article'
                            st.rerun()

def show_article_view():
    article = st.session_state.current_article
    
    col1, col2 = st.columns([1, 8])
    with col1:
        if st.button("← Back"):
            st.session_state.view_mode = 'dashboard'
            st.rerun()
            
    if article:
        # Main Content
        st.title(clean_title(article))
        st.caption(f"Original Link: {article.get('url')}")
        
        st.markdown("---")
        
        # Tabs
        tab1, tab2, tab3 = st.tabs(["📖 Reader View", "🧬 Raw Metadata", "🌐 HTML Source"])
        
        with tab1:
            # Clean up markdown slightly
            content = article.get('markdown', '')
            # Remove excessive newlines
            content = content.replace('\n\n\n', '\n\n')
            st.markdown(content)
            
        with tab2:
            st.json(article)

        with tab3:
            st.code(article.get('html', ''), language='html')

# --- Router ---
if st.session_state.view_mode == 'dashboard':
    show_dashboard()
else:
    show_article_view()
