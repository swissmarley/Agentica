import streamlit as st
import os
from agent import AgentOrchestrator # The new class above

agent = AgentOrchestrator()

st.set_page_config(page_title="Sentinel AI", page_icon="🤖")

st.title("🤖 Sentinel AI: Security Orchestrator")

# Sidebar for explicit File Upload (Standard reliable UI pattern)
with st.sidebar:
    st.header("📁 File Evidence")
    uploaded_file = st.file_uploader("Upload suspicious file")
    if uploaded_file and st.button("Analyze File"):
        with st.spinner("Agent is analyzing file structure..."):
            result = agent.handle_file_upload(uploaded_file.name, uploaded_file.getvalue())
            
            st.markdown("### 📝 AI Assessment")
            st.info(result['summary'])
            
            with open(result['pdf'], "rb") as f:
                st.download_button("Download Report", f, "report.pdf")
            os.remove(result['pdf'])

# Main Chat Interface
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Handle User Input
if prompt := st.chat_input("Ex: 'Is google.com safe?' or 'What is a trojan?'"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            # Pass text to Orchestrator
            response = agent.handle_text_input(prompt)
            
            if response["type"] == "chat":
                st.markdown(response["message"])
                st.session_state.messages.append({"role": "assistant", "content": response["message"]})
            
            elif response["type"] == "report":
                # Display the AI Summary
                st.markdown(f"**Target:** `{response['target']}`")
                st.success(response['summary'])
                
                # Provide PDF
                with open(response['pdf'], "rb") as f:
                    st.download_button("Download PDF Report", f, "scan_report.pdf")
                
                st.session_state.messages.append({"role": "assistant", "content": response['summary']})
                os.remove(response['pdf'])
