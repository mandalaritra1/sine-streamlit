import numpy as np
import streamlit as st

st.title("Sine playground")

f = st.slider("frequency", 0.1, 5.0, 1.0, 0.1)
A = st.slider("amplitude", 0.1, 5.0, 1.0, 0.1)

x = np.linspace(0, 10, 500)
st.line_chart({"y": A * np.sin(f * x)})
