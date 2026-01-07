<script setup>
import { ref, nextTick } from 'vue'
import axios from 'axios'
import { API_BASE_URL } from '../config'

// Generate unique session ID
const generateSessionId = () => {
  return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9)
}

const sessionId = ref(generateSessionId())
const messages = ref([
  { role: 'system', text: 'Hello! Ask me anything about alloys in the database. I can remember our conversation!' }
])
const input = ref('')
const loading = ref(false)
const messagesContainer = ref(null)
const inputField = ref(null)

const scrollToBottom = async () => {
  await nextTick()
  if (messagesContainer.value) {
    const container = messagesContainer.value
    container.scrollTop = container.scrollHeight
  }
}

const focusInput = async () => {
  await nextTick()
  if (inputField.value) {
    inputField.value.focus()
  }
}

const sendMessage = async () => {
  if (!input.value.trim()) return

  // Add user message
  const userMessage = { role: 'user', text: input.value }
  messages.value.push(userMessage)
  const prompt = input.value
  input.value = ''
  loading.value = true

  try {
    // Build conversation history for context
    // Include both user messages and assistant (system) responses
    const history = messages.value
      .slice(0, -1) // Exclude the current message we just added
      .map(m => ({
        role: m.role === 'system' ? 'assistant' : m.role,
        content: m.text
      }))
    
    const res = await axios.post(`${API_BASE_URL}/api/chat`, { 
      prompt,
      sessionId: sessionId.value,
      history: history
    })
    
    // Store the full response (with metadata) for context
    const fullResponse = res.data.result
    
    // Remove metadata from display: [Queried alloys: ...]
    const displayResponse = fullResponse.replace(/^\[Queried alloys:[^\]]+\]\n\n/i, '')
    
    messages.value.push({ 
      role: 'system', 
      text: fullResponse,
      display: displayResponse
    })
    scrollToBottom()
    focusInput()
  } catch (error) {
    messages.value.push({ role: 'system', text: 'Error: ' + error.message })
    scrollToBottom()
    focusInput()
  } finally {
    loading.value = false
  }
}

const clearChat = () => {
  sessionId.value = generateSessionId()
  messages.value = [
    { role: 'system', text: 'New conversation started! Ask me anything about alloys.' }
  ]
  scrollToBottom()
  focusInput()
}
</script>

<template>
  <div class="chat-container">
    <h2>🔬 Research Knowledge Graph</h2>
    <div ref="messagesContainer" class="messages">
      <div 
        v-for="(msg, i) in messages" 
        :key="i" 
        :class="['message', msg.role]"
      >
        <div class="bubble">{{ msg.display || msg.text }}</div>
      </div>
      <div v-if="loading" class="message system">
        <div class="bubble">Thinking... 🧠</div>
      </div>
    </div>
    
    <div class="input-area">
      <button @click="clearChat" class="clear-btn" title="Start new conversation">
        🔄 New Chat
      </button>
      <input 
        ref="inputField"
        v-model="input" 
        @keyup.enter="sendMessage" 
        :disabled="loading"
        placeholder="Ask about alloy properties, compositions, or characteristics..." 
      />
      <button @click="sendMessage" :disabled="loading" class="send-btn">
        {{ loading ? 'Searching...' : 'Send' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.chat-container {
  display: flex;
  flex-direction: column;
  height: 70vh;
  background: var(--bg-card);
  backdrop-filter: blur(20px);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xl);
  padding: var(--space-xl);
  box-shadow: var(--shadow-lg);
}

h2 {
  margin: 0 0 var(--space-lg) 0;
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  color: var(--text-primary);
}

.messages {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  padding: var(--space-md);
  background: rgba(0, 0, 0, 0.2);
  border-radius: var(--radius-lg);
}

.message {
  display: flex;
  animation: fadeIn 0.3s ease-in;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.message.user {
  justify-content: flex-end;
}

.message.system {
  justify-content: flex-start;
}

.bubble {
  padding: var(--space-md) var(--space-lg);
  border-radius: var(--radius-lg);
  max-width: 80%;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.user .bubble {
  background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%);
  color: white;
  box-shadow: var(--shadow-md);
}

.system .bubble {
  background: var(--bg-glass);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: var(--text-primary);
  box-shadow: var(--shadow-sm);
}

.input-area {
  display: flex;
  gap: var(--space-md);
  margin-top: var(--space-lg);
  padding-top: var(--space-lg);
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

input {
  flex: 1;
  padding: var(--space-md) var(--space-lg);
  border-radius: var(--radius-md);
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: var(--bg-glass);
  color: var(--text-primary);
  font-size: var(--font-size-md);
  transition: all var(--transition-base);
}

input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

input::placeholder {
  color: var(--text-muted);
}

button {
  padding: var(--space-md) var(--space-xl);
  border-radius: var(--radius-md);
  border: none;
  font-weight: var(--font-weight-semibold);
  cursor: pointer;
  transition: all var(--transition-base);
}

.clear-btn {
  background: var(--bg-glass);
  color: var(--text-primary);
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.clear-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
  transform: scale(1.05);
}

.send-btn {
  background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%);
  color: white;
  box-shadow: var(--shadow-md);
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}

button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
