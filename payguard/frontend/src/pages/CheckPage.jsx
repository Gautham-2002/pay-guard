import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import {
  Shield, Link2, CreditCard, QrCode,
  Upload, Image as ImageIcon, X,
  ChevronDown, AlertCircle, Loader2
} from 'lucide-react'
import './CheckPage.css'

const SOURCE_TYPES = [
  { value: 'whatsapp_unknown', label: 'WhatsApp from unknown number' },
  { value: 'whatsapp_known',   label: 'WhatsApp from known contact' },
  { value: 'website',          label: 'Website link' },
  { value: 'sms',              label: 'SMS' },
  { value: 'email',            label: 'Email' },
  { value: 'in_person',        label: 'In person' },
  { value: 'marketplace',      label: 'OLX / marketplace' },
  { value: 'other',            label: 'Other' },
]

const TABS = [
  { id: 'url',  label: 'URL / Link', icon: Link2 },
  { id: 'upi',  label: 'UPI ID',     icon: CreditCard },
  { id: 'qr',   label: 'QR Code',    icon: QrCode },
]

export default function CheckPage() {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('url')
  const [paymentUrl, setPaymentUrl]   = useState('')
  const [upiId, setUpiId]             = useState('')
  const [qrFile, setQrFile]           = useState(null)
  const [qrPreview, setQrPreview]     = useState(null)
  const [amount, setAmount]           = useState('')
  const [product, setProduct]         = useState('')
  const [sourceType, setSourceType]   = useState('whatsapp_unknown')
  const [context, setContext]         = useState('')
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState(null)
  const [dragOver, setDragOver]       = useState(false)
  const fileInputRef = useRef()

  const hasDestination =
    (activeTab === 'url' && paymentUrl.trim()) ||
    (activeTab === 'upi' && upiId.trim()) ||
    (activeTab === 'qr' && qrFile)

  function handleQrFile(file) {
    if (!file) return
    setQrFile(file)
    const reader = new FileReader()
    reader.onload = (e) => setQrPreview(e.target.result)
    reader.readAsDataURL(file)
  }

  function handleDrop(e) {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file && file.type.startsWith('image/')) handleQrFile(file)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!hasDestination || !amount || loading) return
    setError(null)
    setLoading(true)

    try {
      const fd = new FormData()
      if (activeTab === 'url') fd.append('payment_url', paymentUrl)
      if (activeTab === 'upi') fd.append('upi_id', upiId)
      if (activeTab === 'qr' && qrFile) fd.append('qr_image', qrFile)
      fd.append('amount', amount)
      fd.append('source_type', sourceType)
      if (product) fd.append('product_description', product)
      if (context) fd.append('additional_context', context)

      const res = await axios.post('/api/check', fd, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })

      navigate(`/analysis/${res.data.txn_id}`)
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Something went wrong'
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg))
      setLoading(false)
    }
  }

  return (
    <div className="check-page">
      <div className="check-container">
        {/* ── Header ── */}
        <motion.div
          className="check-header"
          initial={{ opacity: 0, y: -16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          <div className="header-shield">
            <Shield size={32} strokeWidth={2} />
          </div>
          <h1 className="header-title">PayGuard <span>AI</span></h1>
          <p className="header-tagline">Check before you pay.</p>
          <p className="header-sub">
            AI-powered fraud detection — 4 agents analyze every payment in real time.
          </p>
        </motion.div>

        {/* ── Form ── */}
        <motion.form
          className="glass check-card"
          onSubmit={handleSubmit}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.1 }}
        >
          {/* Section 1 — Destination */}
          <div className="form-section">
            <div className="section-label">
              <span className="section-num">01</span>
              Payment Destination <span className="required">*</span>
            </div>

            {/* Tab switcher */}
            <div className="tab-switcher">
              {TABS.map(tab => (
                <button
                  key={tab.id}
                  type="button"
                  className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
                  onClick={() => setActiveTab(tab.id)}
                >
                  <tab.icon size={14} />
                  {tab.label}
                </button>
              ))}
            </div>

            <AnimatePresence mode="wait">
              {activeTab === 'url' && (
                <motion.div key="url" {...tabAnim}>
                  <input
                    id="payment-url"
                    type="url"
                    className="form-input"
                    placeholder="https://example.com/pay"
                    value={paymentUrl}
                    onChange={e => setPaymentUrl(e.target.value)}
                  />
                </motion.div>
              )}

              {activeTab === 'upi' && (
                <motion.div key="upi" {...tabAnim}>
                  <input
                    id="upi-id"
                    type="text"
                    className="form-input"
                    placeholder="merchant@paytm"
                    value={upiId}
                    onChange={e => setUpiId(e.target.value)}
                  />
                </motion.div>
              )}

              {activeTab === 'qr' && (
                <motion.div key="qr" {...tabAnim}>
                  {qrPreview ? (
                    <div className="qr-preview-wrap">
                      <img src={qrPreview} alt="QR preview" className="qr-preview" />
                      <div className="qr-preview-info">
                        <ImageIcon size={14} />
                        {qrFile?.name}
                      </div>
                      <button
                        type="button"
                        className="qr-remove"
                        onClick={() => { setQrFile(null); setQrPreview(null) }}
                      >
                        <X size={14} /> Remove
                      </button>
                    </div>
                  ) : (
                    <div
                      id="qr-dropzone"
                      className={`qr-dropzone ${dragOver ? 'drag-over' : ''}`}
                      onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                      onDragLeave={() => setDragOver(false)}
                      onDrop={handleDrop}
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <Upload size={28} className="dropzone-icon" />
                      <p className="dropzone-text">Drop QR code image here</p>
                      <p className="dropzone-sub">or click to upload</p>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/*"
                        style={{ display: 'none' }}
                        onChange={e => handleQrFile(e.target.files[0])}
                      />
                    </div>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Section 2 — Payment Details */}
          <div className="form-section">
            <div className="section-label">
              <span className="section-num">02</span>
              Payment Details
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label" htmlFor="amount">Amount (INR) *</label>
                <div className="amount-wrap">
                  <span className="amount-prefix">₹</span>
                  <input
                    id="amount"
                    type="number"
                    min="1"
                    step="0.01"
                    className="form-input amount-input"
                    placeholder="0.00"
                    value={amount}
                    onChange={e => setAmount(e.target.value)}
                    required
                  />
                </div>
              </div>
              <div className="form-group flex-2">
                <label className="form-label" htmlFor="product">
                  What are you paying for?{' '}
                  <span className="label-hint">(helps us check if the price is fair)</span>
                </label>
                <input
                  id="product"
                  type="text"
                  className="form-input"
                  placeholder="e.g. iPhone 15, Freelance work"
                  value={product}
                  onChange={e => setProduct(e.target.value)}
                />
              </div>
            </div>
          </div>

          {/* Section 3 — Source */}
          <div className="form-section">
            <div className="section-label">
              <span className="section-num">03</span>
              How You Received This
            </div>
            <div className="select-wrap">
              <select
                id="source-type"
                className="form-select"
                value={sourceType}
                onChange={e => setSourceType(e.target.value)}
              >
                {SOURCE_TYPES.map(s => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
              <ChevronDown size={16} className="select-arrow" />
            </div>
            <textarea
              id="additional-context"
              className="form-textarea"
              rows={3}
              placeholder="e.g. They said it's for a refund, I'm buying a phone from OLX"
              value={context}
              onChange={e => setContext(e.target.value)}
              style={{ marginTop: 10, resize: 'vertical' }}
            />
          </div>

          {/* Error */}
          <AnimatePresence>
            {error && (
              <motion.div
                className="form-error"
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
              >
                <AlertCircle size={15} />
                {error}
              </motion.div>
            )}
          </AnimatePresence>

          {/* CTA */}
          <button
            id="analyze-btn"
            type="submit"
            className="btn-primary analyze-btn"
            disabled={!hasDestination || !amount || loading}
          >
            {loading ? (
              <><Loader2 size={18} className="spin-icon" /> Submitting...</>
            ) : (
              <>🛡️ Analyze Now</>
            )}
          </button>
        </motion.form>

        {/* Trust badges */}
        <motion.div
          className="trust-badges"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.4 }}
        >
          {['🔍 Destination Intel', '📷 QR & UPI Check', '🌐 Web Search', '⚖️ AI Verdict'].map(b => (
            <span key={b} className="trust-badge">{b}</span>
          ))}
        </motion.div>
      </div>
    </div>
  )
}

const tabAnim = {
  initial: { opacity: 0, x: 8 },
  animate: { opacity: 1, x: 0 },
  exit:    { opacity: 0, x: -8 },
  transition: { duration: 0.15 }
}
