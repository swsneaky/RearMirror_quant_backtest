import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

interface FactorGroupSelectProps {
  options: string[];
  value: string[];
  onChange: (nextValue: string[]) => void;
}

export function FactorGroupSelect({ options, value, onChange }: FactorGroupSelectProps) {
  const toggle = (factorGroup: string) => {
    if (value.includes(factorGroup)) {
      onChange(value.filter((item) => item !== factorGroup));
      return;
    }
    onChange([...value, factorGroup]);
  };

  return (
    <div className="flex flex-wrap gap-2">
      {options.map((factorGroup) => {
        const selected = value.includes(factorGroup);
        return (
          <Button
            key={factorGroup}
            type="button"
            variant={selected ? 'default' : 'outline'}
            size="sm"
            onClick={() => toggle(factorGroup)}
          >
            {factorGroup}
          </Button>
        );
      })}
      {value.length === 0 && (
        <Badge variant="destructive">No factor group selected</Badge>
      )}
    </div>
  );
}
