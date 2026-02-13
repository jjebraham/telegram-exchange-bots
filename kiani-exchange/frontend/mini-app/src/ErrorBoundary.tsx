import React from 'react';

interface Props {
  children: React.ReactNode;
}

interface State {
  hasError: boolean;
  message: string;
}

export default class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, message: '' };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error?.message || 'Unknown error' };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('Mini-app fatal render error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-gray-100 flex items-center justify-center p-6">
          <div className="bg-white rounded-2xl shadow-lg p-6 max-w-md text-center">
            <h2 className="text-xl font-bold text-gray-800 mb-3">KIANI Exchange</h2>
            <p className="text-red-600 text-sm mb-2">خطا در بارگذاری برنامه</p>
            <p className="text-gray-600 text-xs mb-4" dir="ltr">{this.state.message}</p>
            <button
              className="bg-blue-600 text-white px-4 py-2 rounded-lg"
              onClick={() => window.location.reload()}
            >
              بارگذاری مجدد
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
