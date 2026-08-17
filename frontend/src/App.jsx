import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Camera, Save, Scissors, Play, CheckCircle, AlertTriangle, ArrowLeft } from 'lucide-react';

export default function App() {
  const [clips, setClips] = useState([]);
  const [selectedFile, setSelectedFile] = useState('');
  const [availableFiles, setAvailableFiles] = useState([]);
  const [frameData, setFrameData] = useState(null);
  const [bonnetY, setBonnetY] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [processingStatus, setProcessingStatus] = useState('');
  
  // Progress State
  const [isProcessing, setIsProcessing] = useState(false);
  const [progressData, setProgressData] = useState({
    overall_percent: 0,
    clips: {},
    done: false,
    error: null
  });

  const canvasRef = useRef(null);
  const imageRef = useRef(null);
  const bonnetYRef = useRef(null);
  const frameHeightRef = useRef(1944);
  const frameWidthRef = useRef(2592);

  useEffect(() => { bonnetYRef.current = bonnetY; }, [bonnetY]);

  // Fetch available files
  useEffect(() => {
    fetch('/api/files')
      .then(res => res.json())
      .then(data => {
        if (data.files) {
          setAvailableFiles(data.files);
          if (data.files.length > 0) setSelectedFile(data.files[0]);
        }
      });
  }, []);

  const drawCanvas = useCallback(() => {
    const img = imageRef.current;
    const canvas = canvasRef.current;
    const yVal = bonnetYRef.current;
    const origW = frameWidthRef.current;
    const origH = frameHeightRef.current;
    if (!img || !canvas || yVal === null) return;

    const ctx = canvas.getContext('2d');
    const maxWidth = 1200;
    const scale = Math.min(1, maxWidth / img.width);
    canvas.width = img.width * scale;
    canvas.height = img.height * scale;

    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    const drawScale = canvas.height / origH;
    const displayY = yVal * drawScale;
    const nativeCropH = origW / (16 / 9);
    const topY = Math.max(0, yVal - nativeCropH);
    const displayTopY = topY * drawScale;

    ctx.fillStyle = 'rgba(0,0,0,0.35)';
    ctx.fillRect(0, 0, canvas.width, displayTopY);
    ctx.fillRect(0, displayY, canvas.width, canvas.height - displayY);

    ctx.beginPath();
    ctx.moveTo(0, displayY);
    ctx.lineTo(canvas.width, displayY);
    ctx.strokeStyle = '#22c55e';
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.fillStyle = '#22c55e';
    ctx.font = 'bold 14px sans-serif';
    ctx.fillText(`Bonnet Y: ${Math.round(yVal)}`, 10, displayY - 8);

    ctx.beginPath();
    ctx.moveTo(0, displayTopY);
    ctx.lineTo(canvas.width, displayTopY);
    ctx.strokeStyle = '#0ea5e9';
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = '#0ea5e9';
    ctx.fillText(`Top Y: ${Math.round(topY)}`, 10, displayTopY + 16);
  }, []);

  const loadFrame = async () => {
    if (!selectedFile) return;
    setProcessingStatus('Extracting frame...');
    try {
      const res = await fetch('/api/frame', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file: selectedFile })
      });
      const data = await res.json();
      if (data.error) {
        setProcessingStatus(`Error: ${data.error}`);
        return;
      }
      const img = new Image();
      img.src = `data:image/jpeg;base64,${data.image_b64}`;
      img.onload = () => {
        imageRef.current = img;
        frameHeightRef.current = data.height;
        frameWidthRef.current = data.width;
        const defaultY = data.height * 0.75;
        bonnetYRef.current = defaultY;
        setBonnetY(defaultY);
        setFrameData('loaded');
        setProcessingStatus('');
        drawCanvas();
      };
    } catch (e) {
      setProcessingStatus('Failed to load frame');
    }
  };

  useEffect(() => { drawCanvas(); }, [bonnetY, frameData, drawCanvas]);

  const updateY = (e) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const ratio = (e.clientY - rect.top) / rect.height;
    const h = frameHeightRef.current;
    const newY = Math.max(0, Math.min(h, ratio * h));
    bonnetYRef.current = newY;
    setBonnetY(newY);
  };

  const saveClip = () => {
    if (!selectedFile || bonnetY === null) return;
    setClips(prev => [...prev, { file: selectedFile, bonnetY: Math.round(bonnetY) }]);
    setFrameData(null);
    setBonnetY(null);
    imageRef.current = null;
  };

  const submitAll = async () => {
    setIsProcessing(true);
    setProgressData({ overall_percent: 0, clips: {}, done: false, error: null });
    
    try {
      await fetch('/api/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clips })
      });
      
      // Start SSE listening
      const es = new EventSource('/api/progress');
      es.onmessage = (e) => {
        const data = JSON.parse(e.data);
        setProgressData(data);
        if (data.done) es.close();
      };
      es.onerror = () => es.close();

    } catch (e) {
      setProgressData(p => ({ ...p, error: 'Failed to submit pipeline.' }));
    }
  };

  if (isProcessing) {
    return (
      <div style={{ maxWidth: 800, margin: '50px auto', padding: '20px', background: '#1e293b', borderRadius: '8px' }}>
        <h2>Processing {clips.length} Clip(s)</h2>
        
        {/* Master Progress */}
        <div style={{ marginBottom: '30px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span>Overall Progress</span>
            <span style={{ fontWeight: 'bold' }}>{progressData.overall_percent}%</span>
          </div>
          <div style={{ width: '100%', height: '12px', background: '#334155', borderRadius: '6px', overflow: 'hidden' }}>
            <div style={{ width: `${progressData.overall_percent}%`, height: '100%', background: '#2563eb', transition: 'width 0.5s ease-out' }} />
          </div>
        </div>

        {/* Individual Clips */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
          {clips.map(c => {
            const stat = progressData.clips[c.file] || { phase: 'Waiting...', percent: 0 };
            return (
              <div key={c.file} style={{ background: '#0f172a', padding: '15px', borderRadius: '6px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '14px' }}>
                  <span style={{ color: '#cbd5e1' }}>{c.file}</span>
                  <span style={{ color: '#94a3b8' }}>{stat.phase}</span>
                </div>
                <div style={{ width: '100%', height: '8px', background: '#334155', borderRadius: '4px', overflow: 'hidden' }}>
                  <div style={{ width: `${stat.percent}%`, height: '100%', background: '#22c55e', transition: 'width 0.5s ease-out' }} />
                </div>
              </div>
            );
          })}
        </div>

        {/* Completion State */}
        {progressData.done && !progressData.error && (
          <div style={{ marginTop: '30px' }}>
            <div style={{ padding: '15px', background: '#064e3b', color: '#34d399', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '15px' }}>
              <CheckCircle /> Pipeline Complete! Final video stitched successfully.
            </div>
            {progressData.final_video_url && (
              <div style={{ background: '#0f172a', padding: '15px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                <h3 style={{ marginTop: 0, marginBottom: '10px', color: '#e2e8f0', fontSize: '16px' }}>Result Preview</h3>
                <video 
                  src={`http://localhost:8000${progressData.final_video_url}`} 
                  controls 
                  style={{ width: '100%', borderRadius: '4px' }}
                />
              </div>
            )}
          </div>
        )}

        {/* Error State */}
        {progressData.error && (
          <div style={{ marginTop: '30px', padding: '15px', background: '#7f1d1d', color: '#fca5a5', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <AlertTriangle /> {progressData.error}
          </div>
        )}

        {progressData.done && (
          <button 
            onClick={() => { setIsProcessing(false); setClips([]); }} 
            style={{ marginTop: '20px', padding: '10px 20px', background: '#334155', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px' }}
          >
            <ArrowLeft size={16} /> Process More Clips
          </button>
        )}
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', padding: '20px' }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '20px' }}>
        <Camera size={32} />
        <h1>Dashcam Smart Editor UI</h1>
      </header>
      <div style={{ display: 'flex', gap: '20px' }}>
        <div style={{ flex: 2 }}>
          <div style={{ background: '#1e293b', padding: '20px', borderRadius: '8px', marginBottom: '20px' }}>
            <h3>1. Select Clip</h3>
            <div style={{ display: 'flex', gap: '10px' }}>
              <select value={selectedFile} onChange={e => setSelectedFile(e.target.value)} style={{ flex: 1, padding: '10px', background: '#334155', color: '#fff', border: 'none', borderRadius: '4px' }}>
                {availableFiles.map(f => <option key={f} value={f}>{f}</option>)}
              </select>
              <button onClick={loadFrame} style={{ padding: '10px 20px', background: '#2563eb', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>Load Frame</button>
            </div>
          </div>
          {frameData && (
            <div style={{ background: '#1e293b', padding: '20px', borderRadius: '8px' }}>
              <h3>2. Adjust Bonnet Line</h3>
              <p style={{ color: '#94a3b8' }}>Click or drag the green line to the bonnet edge.</p>
              <canvas
                ref={canvasRef}
                onPointerDown={(e) => { setIsDragging(true); updateY(e); }}
                onPointerMove={(e) => { if (isDragging) updateY(e); }}
                onPointerUp={() => setIsDragging(false)}
                onPointerLeave={() => setIsDragging(false)}
                style={{ width: '100%', cursor: 'crosshair', border: '1px solid #475569', borderRadius: '4px' }}
              />
              <div style={{ marginTop: '20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '18px', color: '#22c55e' }}>Bonnet Y: {bonnetY !== null ? Math.round(bonnetY) : '—'}</span>
                <button onClick={saveClip} style={{ display: 'flex', alignItems: 'center', gap: '5px', padding: '10px 20px', background: '#10b981', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}><Save size={18} /> Save & Queue</button>
              </div>
            </div>
          )}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ background: '#1e293b', padding: '20px', borderRadius: '8px', height: '100%' }}>
            <h3><Scissors size={20} style={{ verticalAlign: 'middle', marginRight: '8px' }} />Queue ({clips.length})</h3>
            <ul style={{ listStyle: 'none', padding: 0, margin: '20px 0' }}>
              {clips.map((c, i) => (
                <li key={i} style={{ background: '#334155', padding: '10px', marginBottom: '10px', borderRadius: '4px', fontSize: '14px' }}>
                  <div style={{ wordBreak: 'break-all' }}>{c.file}</div>
                  <div style={{ color: '#22c55e', marginTop: '5px' }}>Crop Y: {c.bonnetY}</div>
                </li>
              ))}
              {clips.length === 0 && <li style={{ color: '#94a3b8' }}>No clips added yet.</li>}
            </ul>
            <button onClick={submitAll} disabled={clips.length === 0} style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '5px', padding: '12px', background: clips.length ? '#f59e0b' : '#475569', color: 'white', border: 'none', borderRadius: '4px', cursor: clips.length ? 'pointer' : 'not-allowed', fontWeight: 'bold' }}>
              <Play size={18} /> Run Smart Editor
            </button>
            {processingStatus && <div style={{ marginTop: '15px', padding: '10px', background: '#334155', borderRadius: '4px', color: '#38bdf8' }}>{processingStatus}</div>}
          </div>
        </div>
      </div>
    </div>
  );
}
