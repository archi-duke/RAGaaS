import { AlertCircle, CheckCircle, Info } from 'lucide-react';

interface MessageDialogProps {
    isOpen: boolean;
    title: string;
    message: string;
    type?: 'info' | 'success' | 'error';
    onClose: () => void;
}

export default function MessageDialog({
    isOpen,
    title,
    message,
    type = 'info',
    onClose
}: MessageDialogProps) {
    if (!isOpen) return null;

    const getIcon = () => {
        switch (type) {
            case 'success':
                return <CheckCircle size={32} className="text-green-500" />;
            case 'error':
                return <AlertCircle size={32} className="text-red-500" />;
            default:
                return <Info size={32} className="text-blue-500" />;
        }
    };

    return (
        <div style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 60
        }} onClick={onClose}>
            <div className="card" style={{ width: '100%', maxWidth: '400px', textAlign: 'center' }} onClick={(e) => e.stopPropagation()}>
                <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '1rem' }}>
                    {getIcon()}
                </div>
                <h3 style={{ marginTop: 0, marginBottom: '0.5rem' }}>{title}</h3>
                <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
                    {message}
                </p>
                <div style={{ display: 'flex', justifyContent: 'center' }}>
                    <button className="btn btn-primary" onClick={onClose}>
                        OK
                    </button>
                </div>
            </div>
        </div>
    );
}
