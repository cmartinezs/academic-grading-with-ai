Algoritmo DespachoPedido
	Definir saldo, compra, restante Como Real
	Escribir "Inicio del proceso de despacho"
	Escribir "Ingrese saldo disponible"
	Leer saldo
	Escribir "Ingrese monto de compra"
	Leer compra
	Si saldo >= compra Entonces
		restante <- saldo - compra
		Escribir "Pedido aprobado"
		Escribir "Saldo restante: ", restante
	SiNo
		Escribir "Pedido rechazado"
	FinSi
	Escribir "Fin del proceso"
FinAlgoritmo
