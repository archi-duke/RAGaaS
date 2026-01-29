
interface ConfirmDialogProps {
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
    onCancel: () => void;
    confirmText?: string;
    cancelText?: string;
    isDestructive?: boolean;
}

export default function ConfirmDialog({
    isOpen,
    title,
    message,
    onConfirm,
    onCancel,
    confirmText = 'Confirm',
    cancelText = 'Cancel',
    isDestructive = false
}: ConfirmDialogProps) {
    if (!isOpen) return null;

    return (
        <div style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 50
        }} onClick={onCancel}>
            <div className="card" style={{ width: '100%', maxWidth: '400px', textAlign: 'center' }} onClick={(e) => e.stopPropagation()}>
                <h3 style={{ marginTop: 0 }}>{title}</h3>
                <p style={{ color: 'var(--text-secondary)' }}>
                    {message}
                </p>
                <div style={{ display: 'flex', justifyContent: 'center', gap: '1rem', marginTop: '1.5rem' }}>
                    <button className="btn" onClick={onCancel}>
                        {cancelText}
                    </button>
                    <button
                        className="btn"
                        style={{
                            background: isDestructive ? 'var(--danger)' : 'var(--primary)',
                            color: 'white'
                        }}
                        onClick={onConfirm}
                    >
                        {confirmText}
                    </button>
                </div>
            </div>
        </div>
    );
}
