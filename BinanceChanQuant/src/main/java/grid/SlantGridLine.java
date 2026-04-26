package grid;

public class SlantGridLine {
    public double basePrice;
    public double slope;
    public int index;

    public double getNowPrice(long nowKIndex) {
        return basePrice + slope * nowKIndex;
    }
}
