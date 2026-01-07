<script setup>
import { ref, nextTick } from 'vue'
import axios from 'axios'

import { API_BASE_URL } from '../config'
import AlloyCard from './AlloyCard.vue'

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
const emit = defineEmits(['design'])

// UI State
const isExpanded = ref(false)
const toggleExpand = () => {
  isExpanded.value = !isExpanded.value
  scrollToBottom()
}

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

  // 1. Add User Message
  const prompt = input.value
  messages.value.push({ role: 'user', text: prompt })
  input.value = ''
  loading.value = true
  
  // Assistant message will be created when first chunk arrives
  let assistantMsg = null
  scrollToBottom()

  try {
    // 3. Prepare History
    const history = messages.value
      .slice(0, -1)  // Exclude only current user message
      .map(m => ({
        role: m.role === 'system' ? 'assistant' : m.role,
        content: m.text
      }))

    // 4. Start Streaming Request
    const response = await fetch(`${API_BASE_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        prompt, 
        sessionId: sessionId.value, 
        history 
      })
    })

    if (!response.ok) throw new Error(response.statusText)

    // 5. Read stream
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() // Keep incomplete line in buffer

      for (const line of lines) {
        if (!line.trim()) continue
        try {
          const chunk = JSON.parse(line)
          
          // Create assistant message on first chunk (avoids empty bubble)
          if (!assistantMsg && (chunk.type === 'data' || chunk.type === 'chunk')) {
            assistantMsg = {
              role: 'assistant',
              display: '',
              text: '',
              alloys: [],
              toolSuggestion: null
            }
            messages.value.push(assistantMsg)
          }
          
          if (chunk.type === 'data') {
            // Received Alloy Data
            assistantMsg.alloys = chunk.alloys || []
          } 
          else if (chunk.type === 'chunk' || chunk.type === 'text_chunk' || chunk.type === 'string_chunk') {
            // Received Text Chunk
            assistantMsg.display += chunk.content
            assistantMsg.text += chunk.content
            scrollToBottom()
          }
          else if (chunk.type === 'tool_suggestion') {
            // Received Tool Suggestion
            assistantMsg.toolSuggestion = {
              tool: chunk.tool,
              message: chunk.message
            }
          }
          else if (chunk.type === 'error') {
            assistantMsg.display += `\n[Error: ${chunk.content}]`
          }
        } catch (e) {
          // Silently skip malformed chunks
        }
      }
    }
    
    // Final scroll
    scrollToBottom()
    focusInput()

  } catch (error) {
    if (assistantMsg) assistantMsg.display += `\n[Communication Error: ${error.message}]`
    scrollToBottom() 
  } finally {
    loading.value = false
  }
}

const handleToolSuggestion = (tool, msg) => {
  if (tool === 'designer') {
    const payload = (msg.alloys && msg.alloys.length > 0) ? msg.alloys[0] : null
    emit('design', payload)
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
  <div :class="['chat-container', { expanded: isExpanded }]">
    <!-- Header -->
    <div class="chat-header">
      <h2>Research Assistant</h2>
      <button class="expand-btn" @click="toggleExpand" :title="isExpanded ? 'Collapse' : 'Expand'">
        <span class="icon">{{ isExpanded ? '↙️' : '↗️' }}</span>
      </button>
    </div>

    <!-- Messages -->
    <div class="messages" ref="messagesContainer">
      <div v-for="(msg, index) in messages" :key="index" :class="['message', msg.role]">
        <div class="bubble">
          <!-- Text Content -->
          <div class="text-content">{{ msg.display || msg.text }}</div>
          
          <!-- Alloy Data Cards -->
          <div v-if="msg.alloys && msg.alloys.length" class="alloy-list">
            <AlloyCard 
              v-for="alloy in msg.alloys" 
              :key="alloy.name" 
              :alloy="alloy"
              @design="$emit('design', $event)"
            />
          </div>
        </div>
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
  transition: all 0.3s ease;
}

.chat-container.expanded {
  position: fixed;
  top: 20px;
  left: 20px;
  right: 20px;
  bottom: 20px;
  height: auto;
  z-index: 1000;
  border-color: var(--primary);
  box-shadow: 0 0 50px rgba(0,0,0,0.5);
}



.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-lg);
}

.expand-btn {
  background: rgba(255, 255, 255, 0.1);
  padding: var(--space-xs) var(--space-sm);
  font-size: 1.2rem;
  opacity: 0.8;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.expand-btn:hover {
  opacity: 1;
  background: rgba(255, 255, 255, 0.2);
  transform: scale(1.1);
}

h2 {
  margin: 0;
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

.suggestion-btn {
  margin-top: 0.75rem;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: linear-gradient(135deg, var(--secondary) 0%, #8b5cf6 100%);
  color: white;
  border: none;
  padding: 0.6rem 1rem;
  border-radius: var(--radius-md);
  font-size: 0.9rem;
  font-weight: 600;
  box-shadow: var(--shadow-md);
  transition: all 0.2s ease;
}

.suggestion-btn:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
  filter: brightness(1.1);
}

button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.expand-btn {
  background: transparent;
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
  font-size: 1.2rem;
  padding: 0.5rem;
  width: 2.4rem;
  height: 2.4rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  transition: all 0.2s ease;
}

.expand-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-primary);
  border-color: var(--primary);
  transform: scale(1.05);
}
</style>
