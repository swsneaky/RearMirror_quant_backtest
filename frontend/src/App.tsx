import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from '@/components/Layout';
import { Dashboard } from '@/pages/Dashboard';
import { DataLayersPage } from '@/pages/DataLayers';
import { BacktestPage } from '@/pages/Backtest';
import { HPOPage } from '@/pages/HPO';
import { StocksPage } from '@/pages/Stocks';
import { FactorsPage } from '@/pages/Factors';
import { TrainingSetsPage } from '@/pages/TrainingSets';
import { ModelTrainingPage } from '@/pages/ModelTraining';

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/data-layers" element={<DataLayersPage />} />
          <Route path="/stocks" element={<StocksPage />} />
          <Route path="/training-sets" element={<TrainingSetsPage />} />
          <Route path="/model-training" element={<ModelTrainingPage />} />
          <Route path="/backtest" element={<BacktestPage />} />
          <Route path="/hpo" element={<HPOPage />} />
          <Route path="/factors" element={<FactorsPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
